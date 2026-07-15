"""Resolution orchestration: resolve identifiers and apply them to sources.

``resolve_one`` runs the authority chain (cache-first) and stores a
``ResolutionRecord``. ``apply_to_source`` writes back only fields that are
currently ``[VERIFY]``/missing AND clear the confidence threshold — everything
else stays a placeholder (never-guess). Retracted works are flagged and never
auto-verified.
"""

from __future__ import annotations

import re
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.resolution_record import ResolutionRecord
from app.models.source import Source
from app.models.source_field_provenance import SourceFieldProvenance
from app.references import cache
from app.references.http import build_client
from app.references.identifiers import detect_identifier, normalize_freetext
from app.references.reconcile import merge
from app.references.resolvers import REGISTRY
from app.references.resolvers.base import ResolvedRecord
from app.references.retraction import status_from_retraction
from app.renderers.field_schema import _is_missing

__all__ = ["resolve_one", "resolve_batch", "apply_to_source"]


async def _resolve_uncached(
    client: httpx.AsyncClient, id_kind: str, id_value: str, query: str
) -> tuple[list[ResolvedRecord], list[str]]:
    records: list[ResolvedRecord] = []
    tried: list[str] = []
    hint = {"query": query}
    for resolver in REGISTRY:
        if not resolver.handles(id_kind):
            continue
        tried.append(resolver.name)
        record = await resolver.resolve(client, id_kind, id_value, hint)
        if record is not None and record.matched:
            records.append(record)
    return records, tried


async def resolve_one(
    db: AsyncSession,
    query: str,
    *,
    kind_hint: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> ResolutionRecord:
    """Resolve a single query (DOI/arXiv/ISBN/free-text) to a cached record."""
    id_kind, id_value = detect_identifier(query)

    cached = await cache.get(db, id_kind, id_value)
    if cached is not None:
        return cached

    settings = get_settings()
    enabled = client is not None or getattr(settings, "RESOLVER_ENABLED", True)
    if not enabled:
        return await cache.put(
            db, id_kind=id_kind, id_value=id_value, status="unresolved",
            merged=None, authorities_tried=[],
        )

    owns_client = client is None
    active = client or build_client()
    try:
        records, tried = await _resolve_uncached(active, id_kind, id_value, query)
    finally:
        if owns_client:
            await active.aclose()

    if not records:
        return await cache.put(
            db, id_kind=id_kind, id_value=id_value, status="unresolved",
            merged=None, authorities_tried=tried,
        )

    merged = merge(records)
    return await cache.put(
        db, id_kind=id_kind, id_value=id_value, status="resolved",
        merged=merged, authorities_tried=tried,
    )


async def resolve_batch(
    db: AsyncSession,
    queries: list[str],
    *,
    client: httpx.AsyncClient | None = None,
) -> list[ResolutionRecord]:
    """Resolve many queries, reusing one HTTP client across the batch."""
    owns_client = client is None
    active = client or build_client()
    results: list[ResolutionRecord] = []
    try:
        for query in queries:
            results.append(await resolve_one(db, query, client=active))
    finally:
        if owns_client:
            await active.aclose()
    return results


def _canonical_key_from_fields(fields: dict) -> str:
    author = str(fields.get("author") or "")
    surname = author.split(" and ")[0].split(",")[0].strip().lower()
    year = str(fields.get("year") or "").strip()
    title = re.sub(r"[^\w\s]", "", str(fields.get("title") or "").lower())
    title = re.sub(r"\s+", " ", title).strip()[:60]
    return f"{surname}|{year}|{title}"


async def apply_to_source(
    db: AsyncSession,
    source: Source,
    record: ResolutionRecord,
    *,
    min_confidence: float = 0.75,
) -> list[str]:
    """Write resolved fields onto a source under the never-guess discipline.

    Only fields currently missing/``[VERIFY]`` and at or above ``min_confidence``
    are written; each writes a SourceFieldProvenance row. Retracted works are
    flagged and never auto-verified.
    """
    canonical = record.canonical or {}
    provenance = record.provenance or {}
    new_fields = dict(source.fields or {})
    applied: list[str] = []

    for name, value in canonical.items():
        if not _is_missing(new_fields.get(name)):
            continue
        confidence = float((provenance.get(name) or {}).get("confidence", 0.0))
        if confidence < min_confidence:
            continue
        new_fields[name] = value
        applied.append(name)
        db.add(
            SourceFieldProvenance(
                source_id=source.id,
                field_name=name,
                value=value,
                authority=(provenance.get(name) or {}).get("authority", "merged"),
                confidence=confidence,
                resolution_record_id=record.id,
                applied=True,
            )
        )

    if applied:
        source.fields = new_fields
        source.verification_method = "resolver"

    source.resolution_status = record.status
    source.retraction_status = status_from_retraction(record.retraction)
    if source.source_type is None and record.source_type:
        source.source_type = record.source_type
    source.canonical_key = _canonical_key_from_fields(new_fields)

    await db.flush()
    return applied


async def resolve_and_apply(
    db: AsyncSession,
    source: Source,
    *,
    min_confidence: float = 0.75,
    client: httpx.AsyncClient | None = None,
) -> tuple[ResolutionRecord, list[str]]:
    """Resolve the best available identifier for a source and apply it."""
    query = _source_query(source)
    record = await resolve_one(db, query, client=client)
    applied: list[str] = []
    if record.status == "resolved":
        applied = await apply_to_source(db, source, record, min_confidence=min_confidence)
    return record, applied


def _source_query(source: Source) -> str:
    """Best resolution seed for a source: a DOI/URL identifier, else its title."""
    fields = source.fields or {}
    ident = source.identifiers or {}
    for key in ("doi", "doi_or_url", "arxiv", "isbn", "url"):
        value = ident.get(key) or fields.get(key)
        if value:
            return str(value)
    title = str(fields.get("title") or "").strip()
    author = str(fields.get("author") or "").split(" and ")[0]
    return normalize_freetext(f"{title} {author}") or title
