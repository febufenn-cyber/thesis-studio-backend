"""Discovery orchestration: search + add-to-registry."""

from __future__ import annotations

import asyncio
import re
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.source import Source
from app.references.http import build_client
from app.references.identifiers import normalize_freetext
from app.references.search.base import Candidate
from app.references.search.providers import SEARCH_REGISTRY
from app.references.service import apply_to_source, resolve_one

__all__ = ["search", "add_candidate"]


def _dedup_key(candidate: Candidate) -> str:
    if candidate.doi:
        return candidate.doi.strip().lower()
    title = normalize_freetext(candidate.title)[:60]
    return f"{title}|{candidate.year or ''}"


async def search(
    db: AsyncSession,
    query: str,
    *,
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> list[Candidate]:
    """Query authorities for candidates; dedup by DOI/title; never persists."""
    settings = get_settings()
    enabled = client is not None or getattr(settings, "LITERATURE_SEARCH_ENABLED", True)
    if not enabled or not query.strip():
        return []

    owns_client = client is None
    active = client or build_client()
    try:
        results = await asyncio.gather(
            *(provider.search(active, query, limit=limit) for provider in SEARCH_REGISTRY),
            return_exceptions=True,
        )
    finally:
        if owns_client:
            await active.aclose()

    seen: dict[str, Candidate] = {}
    for result in results:
        if isinstance(result, Exception):
            continue
        for candidate in result:
            key = _dedup_key(candidate)
            existing = seen.get(key)
            if existing is None or candidate.score > existing.score:
                seen[key] = candidate
    return sorted(seen.values(), key=lambda c: c.score, reverse=True)[:limit]


async def add_candidate(
    db: AsyncSession,
    project,
    user_id: UUID,
    identifier: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[Source, list[str]]:
    """Resolve an identifier and create a verified registry Source from it."""
    record = await resolve_one(db, identifier, client=client)
    doi = record.canonical.get("doi_or_url") if record.canonical else None
    source = Source(
        project_id=project.id,
        user_id=user_id,
        kind=record.registry_kind or "web",
        source_type=record.source_type,
        fields={},
        identifiers={"doi": doi} if doi and re.match(r"10\.\d", str(doi)) else {},
        verified=False,
        parse_status="imported",
    )
    db.add(source)
    await db.flush()
    applied: list[str] = []
    if record.status == "resolved":
        applied = await apply_to_source(db, source, record)
    return source, applied
