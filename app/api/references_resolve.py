"""Reference-resolution API — resolve [VERIFY] placeholders against authorities.

Owner-guarded like the rest of app.api.projects (foreign project/source → 404).
Resolution never fabricates data: unresolved queries and low-confidence fields
leave the source's ``[VERIFY]`` placeholders in place (DESIGN.md rule 2).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.models.resolution_record import ResolutionRecord
from app.models.source import Source
from app.references import service
from app.renderers.field_schema import missing_required

router = APIRouter(tags=["projects"])

_MAX_BATCH = 2000


class ResolveRequest(BaseModel):
    query: str
    kind_hint: str | None = None


class ResolveBatchRequest(BaseModel):
    queries: list[str]


class SourceResolveRequest(BaseModel):
    min_confidence: float = Field(default=0.75, ge=0.0, le=1.0)


def _serialize(record: ResolutionRecord) -> dict:
    fields: dict[str, dict] = {}
    provenance = record.provenance or {}
    for name, value in (record.canonical or {}).items():
        prov = provenance.get(name, {})
        fields[name] = {
            "value": value,
            "authority": prov.get("authority"),
            "confidence": prov.get("confidence"),
        }
    return {
        "status": record.status,
        "identifier": {"kind": record.identifier_kind, "value": record.identifier_value},
        "fields": fields,
        "source_type": record.source_type,
        "registry_kind": record.registry_kind,
        "retraction": record.retraction,
        "authorities_tried": record.authorities_tried,
    }


@router.post("/projects/{project_id}/references/resolve")
async def resolve_reference(
    project_id: UUID,
    body: ResolveRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resolve a single identifier or free-text citation to verified metadata."""
    await fetch_owned_project(db, project_id, current_user.id)
    record = await service.resolve_one(db, body.query, kind_hint=body.kind_hint)
    await db.commit()
    return _serialize(record)


@router.post("/projects/{project_id}/references/resolve-batch")
async def resolve_reference_batch(
    project_id: UUID,
    body: ResolveBatchRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resolve many queries at once (cache-first, one HTTP client for the batch)."""
    await fetch_owned_project(db, project_id, current_user.id)
    if len(body.queries) > _MAX_BATCH:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Batch exceeds the {_MAX_BATCH}-query limit.",
        )
    records = await service.resolve_batch(db, body.queries)
    await db.commit()
    resolved = sum(1 for r in records if r.status == "resolved")
    return {
        "results": [_serialize(r) for r in records],
        "resolved": resolved,
        "unresolved": len(records) - resolved,
    }


@router.post("/projects/{project_id}/sources/{source_id}/resolve")
async def resolve_source(
    project_id: UUID,
    source_id: UUID,
    body: SourceResolveRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resolve and apply verified metadata to an existing registry source."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    source = (
        await db.execute(
            select(Source).where(Source.id == source_id, Source.project_id == project.id)
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")

    record, applied = await service.resolve_and_apply(
        db, source, min_confidence=body.min_confidence
    )
    still_missing = missing_required(source.kind, source.fields or {})
    await db.commit()
    return {
        "source_id": str(source.id),
        "applied_fields": applied,
        "still_missing": still_missing,
        "resolution_status": source.resolution_status,
        "retraction_status": source.retraction_status,
    }
