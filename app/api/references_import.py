"""Reference-import API — bulk-load BibTeX/RIS into the citation registry.

Imported entries land as UNVERIFIED sources (parse_status="imported"): the
parsers map only the fields the file provides and never invent bibliographic
data (DESIGN.md rule 2); the verifier flags gaps later. Owner-guarded like the
rest of app.api.projects — a foreign project is 404, never 403.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.importers.csl_import import from_csl_json
from app.importers.zotero import ZoteroError, fetch_library, import_zotero
from app.models.source import Source
from app.references.http import build_client
from app.renderers.bibtex_import import from_bibtex
from app.renderers.ris import from_ris


router = APIRouter(tags=["projects"])

# Guardrails: refuse pathological payloads before parsing/inserting.
_MAX_CONTENT_BYTES = 2 * 1024 * 1024  # 2 MB
_MAX_CANDIDATES = 2000


class ReferenceImportRequest(BaseModel):
    format: Literal["bibtex", "ris", "csl"]
    content: str


_PARSERS = {"bibtex": from_bibtex, "ris": from_ris, "csl": from_csl_json}


class ReferenceImportResponse(BaseModel):
    imported: int
    kinds: dict[str, int]


@router.post(
    "/projects/{project_id}/references/import",
    response_model=ReferenceImportResponse,
)
async def import_references(
    project_id: UUID,
    body: ReferenceImportRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ReferenceImportResponse:
    """Parse a BibTeX/RIS document into unverified registry sources."""
    project = await fetch_owned_project(db, project_id, current_user.id)

    if len(body.content.encode("utf-8")) > _MAX_CONTENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Import payload exceeds the 2 MB limit.",
        )

    parse = _PARSERS[body.format]
    candidates = parse(body.content)

    if len(candidates) > _MAX_CANDIDATES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Import exceeds the {_MAX_CANDIDATES}-entry limit.",
        )

    kinds: dict[str, int] = {}
    imported = 0
    for candidate in candidates:
        fields = candidate.get("fields") or {}
        if not fields:
            continue
        kind = candidate["kind"]
        db.add(
            Source(
                project_id=project.id,
                user_id=current_user.id,
                kind=kind,
                fields=fields,
                verified=False,
                parse_status="imported",
            )
        )
        kinds[kind] = kinds.get(kind, 0) + 1
        imported += 1

    await db.commit()
    return ReferenceImportResponse(imported=imported, kinds=kinds)


class ZoteroImportRequest(BaseModel):
    api_key: str
    library_id: str
    library_type: Literal["user", "group"] = "user"
    since_version: int | None = None
    enrich: bool = False


@router.post("/projects/{project_id}/references/zotero/import")
async def import_zotero_library(
    project_id: UUID,
    body: ZoteroImportRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Import a Zotero library (CSL-JSON) as unverified registry sources."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    client = build_client()
    try:
        items, version = await fetch_library(
            client, body.api_key, body.library_id,
            library_type=body.library_type, since_version=body.since_version,
        )
    except ZoteroError as exc:
        await client.aclose()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if len(items) > _MAX_CANDIDATES:
        await client.aclose()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Zotero import exceeds the {_MAX_CANDIDATES}-item limit.",
        )
    try:
        # Reuse the same client for enrichment resolution.
        result = await import_zotero(
            db, project, items, user_id=current_user.id, enrich=body.enrich, client=client
        )
    finally:
        await client.aclose()
    await db.commit()
    result["library_version"] = version
    return result
