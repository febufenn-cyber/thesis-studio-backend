"""Zotero library sync (docs/LLD_MISSING_FEATURES.md MF5).

Pull a user's Zotero library via the Zotero Web API in CSL-JSON and feed it
straight into the existing ``from_csl_json`` mapper — Zotero speaks CSL natively,
so no new parser. Items land as unverified Sources; optional Phase 1 enrichment
fills/verifies fields under the never-guess discipline. Option A (per-request
key): nothing is stored server-side.
"""

from __future__ import annotations

import json
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.importers.csl_import import from_csl_json
from app.models.source import Source
from app.references.http import build_client
from app.references.service import apply_to_source, resolve_one

__all__ = ["fetch_library", "import_zotero", "ZoteroError"]

_MAX_PAGES = 20
_PAGE_SIZE = 100


class ZoteroError(RuntimeError):
    """Zotero API rejected the request (bad key / library)."""


def _extract_items(payload) -> list:
    if isinstance(payload, dict):
        return payload.get("items") or []
    if isinstance(payload, list):
        return payload
    return []


async def fetch_library(
    client: httpx.AsyncClient,
    api_key: str,
    library_id: str,
    *,
    library_type: str = "user",
    since_version: int | None = None,
) -> tuple[list[dict], int | None]:
    """Fetch CSL-JSON items for a Zotero library (paginated). Returns (items, version)."""
    base = f"https://api.zotero.org/{'groups' if library_type == 'group' else 'users'}/{library_id}/items"
    headers = {"Zotero-API-Key": api_key}
    if since_version is not None:
        headers["If-Modified-Since-Version"] = str(since_version)

    items: list[dict] = []
    version: int | None = None
    start = 0
    for _ in range(_MAX_PAGES):
        try:
            response = await client.get(
                base,
                params={"format": "csljson", "limit": str(_PAGE_SIZE), "start": str(start)},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise ZoteroError(str(exc)) from exc
        if response.status_code == 304:
            break  # not modified since cursor
        if response.status_code in (401, 403):
            raise ZoteroError("Zotero rejected the API key or library access.")
        if response.status_code != 200:
            raise ZoteroError(f"Zotero API error: {response.status_code}")

        version_header = response.headers.get("Last-Modified-Version")
        if version_header and version_header.isdigit():
            version = int(version_header)
        try:
            page = _extract_items(response.json())
        except ValueError as exc:
            raise ZoteroError("Malformed Zotero response.") from exc
        items.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return items, version


async def import_zotero(
    db: AsyncSession,
    project,
    items: list[dict],
    *,
    user_id: UUID,
    enrich: bool = False,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Create registry sources from CSL-JSON items; optionally enrich each."""
    candidates = from_csl_json(json.dumps(items))
    kinds: dict[str, int] = {}
    created: list[Source] = []
    for candidate in candidates:
        fields = candidate.get("fields") or {}
        if not fields:
            continue
        kind = candidate["kind"]
        source = Source(
            project_id=project.id,
            user_id=user_id,
            kind=kind,
            fields=fields,
            verified=False,
            parse_status="imported",
        )
        db.add(source)
        kinds[kind] = kinds.get(kind, 0) + 1
        created.append(source)
    await db.flush()

    enriched = 0
    if enrich and created:
        owns = client is None
        active = client or build_client()
        try:
            for source in created:
                query = _source_query(source)
                if not query:
                    continue
                record = await resolve_one(db, query, client=active)
                if record.status == "resolved":
                    applied = await apply_to_source(db, source, record)
                    if applied:
                        enriched += 1
        finally:
            if owns:
                await active.aclose()

    return {"imported": len(created), "kinds": kinds, "enriched": enriched}


def _source_query(source: Source) -> str:
    fields = source.fields or {}
    for key in ("doi_or_url", "url"):
        value = fields.get(key)
        if value and "[VERIFY]" not in str(value):
            return str(value)
    return str(fields.get("title") or "").strip()
