"""Version-safe source and quotation mutations for the Phase 1 workspace.

These routes are registered before the legacy manuscript router equivalents so
new requests cannot verify stale text or mutate an inactive revision's audit
records. Missing expected_version remains tolerated only for legacy callers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.models.event import Event
from app.models.quote import Quote
from app.models.source import Source
from app.schemas.project import SourceResponse, SourceUpdate


router = APIRouter(tags=["phase1"])


class QuoteVerificationUpdate(BaseModel):
    verified: bool
    verification_method: str = Field("manual", min_length=2, max_length=40)
    expected_text: str | None = None
    expected_version: int | None = Field(None, ge=1)


def _assert_version(current: int, expected: int | None) -> None:
    if expected is not None and current != expected:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Project changed in another session. Reload before continuing.",
                "expected_version": expected,
                "current_version": current,
            },
        )


def _is_active_import(row, active_revision_id: UUID | None) -> bool:
    revision_id = getattr(row, "import_revision_id", None)
    return revision_id is None or revision_id == active_revision_id


@router.patch(
    "/projects/{project_id}/sources/{source_id}",
    response_model=SourceResponse,
)
async def update_active_source(
    project_id: UUID,
    source_id: UUID,
    body: SourceUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project.document_version, body.expected_version)
    source = (
        await db.execute(
            select(Source).where(
                Source.id == source_id,
                Source.project_id == project.id,
                Source.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if source is None or not _is_active_import(source, project.active_revision_id):
        raise HTTPException(status_code=404, detail="Active source not found")

    changes = body.model_dump(exclude_unset=True)
    verification_basis_changed = any(
        key in changes for key in ("kind", "fields", "raw_entry", "identifiers")
    )
    for key, value in changes.items():
        setattr(source, key, value)

    if verification_basis_changed and "verified" not in changes:
        source.verified = False
    if source.verified:
        source.verified_at = datetime.now(timezone.utc)
        source.verified_by = current_user.id
        source.verification_method = body.verification_method or "manual"
    else:
        source.verified_at = None
        source.verified_by = None
        if "verification_method" not in changes:
            source.verification_method = None

    project.document_version += 1
    db.add(
        Event(
            project_id=project.id,
            user_id=current_user.id,
            kind="source_updated",
            data={
                "source_id": str(source.id),
                "verified": source.verified,
                "document_version": project.document_version,
            },
        )
    )
    await db.commit()
    await db.refresh(source)
    return source


@router.patch("/projects/{project_id}/quotes/{quote_id}")
async def verify_active_quote(
    project_id: UUID,
    quote_id: UUID,
    body: QuoteVerificationUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project.document_version, body.expected_version)
    quote = (
        await db.execute(
            select(Quote).where(
                Quote.id == quote_id,
                Quote.project_id == project.id,
                Quote.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if quote is None or not _is_active_import(quote, project.active_revision_id):
        raise HTTPException(status_code=404, detail="Active quotation not found")
    if body.expected_text is not None and body.expected_text != quote.text:
        raise HTTPException(
            status_code=409,
            detail="Quotation text changed since it was opened. Reload before verifying.",
        )

    quote.verified = body.verified
    quote.verification_method = body.verification_method if body.verified else None
    quote.verified_at = datetime.now(timezone.utc) if body.verified else None
    quote.verified_by = current_user.id if body.verified else None
    project.document_version += 1
    db.add(
        Event(
            project_id=project.id,
            user_id=current_user.id,
            kind="quotation_verification_changed",
            data={
                "quote_id": str(quote.id),
                "verified": quote.verified,
                "document_version": project.document_version,
            },
        )
    )
    await db.commit()
    return {
        "id": str(quote.id),
        "verified": quote.verified,
        "verified_at": quote.verified_at,
        "document_version": project.document_version,
    }
