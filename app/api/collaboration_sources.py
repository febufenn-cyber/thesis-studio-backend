"""Shared source/quotation review with explicit verification authority."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.collaboration.capabilities import require_project_capability
from app.db.deps import get_db
from app.models.event import Event
from app.models.quote import Quote
from app.models.source import Source
from app.services.registry_scope import active_revision_rows


router = APIRouter(tags=["collaboration"])


class VerificationDecision(BaseModel):
    verified: bool
    method: Literal[
        "student_source_copy", "supervisor_review", "operator_metadata_check",
        "library_catalog", "publisher_metadata", "manual_comparison",
    ]
    note: str = Field(..., min_length=3, max_length=8000)


@router.get("/projects/{project_id}/collaboration/evidence")
async def shared_evidence_registry(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(
        db, project_id, current_user, "project.read_sources"
    )
    all_sources = list(
        (
            await db.execute(select(Source).where(Source.project_id == project_id))
        ).scalars()
    )
    all_quotes = list(
        (
            await db.execute(select(Quote).where(Quote.project_id == project_id))
        ).scalars()
    )
    sources = active_revision_rows(all_sources, access.project.active_revision_id)
    quotes = active_revision_rows(all_quotes, access.project.active_revision_id)
    return {
        "project_id": project_id,
        "active_revision_id": access.project.active_revision_id,
        "verification_authority": "source.verify" in access.capabilities,
        "sources": [
            {
                "id": row.id,
                "kind": row.kind,
                "fields": row.fields,
                "raw_entry": row.raw_entry,
                "parse_status": row.parse_status,
                "identifiers": row.identifiers,
                "verified": row.verified,
                "verify_note": row.verify_note,
                "verification_method": row.verification_method,
                "verified_by": row.verified_by,
                "verified_at": row.verified_at,
                "created_at": row.created_at,
            }
            for row in sources
        ],
        "quotes": [
            {
                "id": row.id,
                "source_id": row.source_id,
                "text": row.text,
                "locator": row.locator,
                "verified": row.verified,
                "verify_note": row.verify_note,
                "verification_method": row.verification_method,
                "verified_by": row.verified_by,
                "verified_at": row.verified_at,
                "created_at": row.created_at,
            }
            for row in quotes
        ],
        "truth_notice": (
            "Verification records internal traceability and human comparison. It does not "
            "prove universal truth, source credibility, originality or interpretive validity."
        ),
    }


@router.post("/projects/{project_id}/collaboration/sources/{source_id}/verification")
async def verify_shared_source(
    project_id: UUID,
    source_id: UUID,
    body: VerificationDecision,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "source.verify")
    row = (
        await db.execute(
            select(Source).where(
                Source.id == source_id,
                Source.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if row is None or (
        access.project.active_revision_id is not None
        and row.manuscript_revision_id not in (None, access.project.active_revision_id)
    ):
        raise HTTPException(status_code=404, detail="Source not found")
    now = datetime.now(timezone.utc)
    row.verified = body.verified
    row.verify_note = body.note
    row.verification_method = body.method
    row.verified_by = current_user.id if body.verified else None
    row.verified_at = now if body.verified else None
    if not body.verified:
        # Dependent exact quotations cannot remain verified after their source is rejected.
        quotes = list(
            (
                await db.execute(
                    select(Quote).where(
                        Quote.project_id == project_id,
                        Quote.source_id == row.id,
                        Quote.verified.is_(True),
                    )
                )
            ).scalars()
        )
        for quote in quotes:
            quote.verified = False
            quote.verified_by = None
            quote.verified_at = None
            quote.verify_note = "Source verification was revoked: " + body.note
    db.add(
        Event(
            project_id=project_id,
            user_id=current_user.id,
            kind="collaboration_source_verification_changed",
            data={
                "source_id": str(row.id),
                "verified": row.verified,
                "method": body.method,
                "document_version": access.project.document_version,
            },
        )
    )
    await db.commit()
    return {
        "id": row.id,
        "verified": row.verified,
        "verification_method": row.verification_method,
        "verified_by": row.verified_by,
        "verified_at": row.verified_at,
    }


@router.post("/projects/{project_id}/collaboration/quotes/{quote_id}/verification")
async def verify_shared_quote(
    project_id: UUID,
    quote_id: UUID,
    body: VerificationDecision,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "source.verify")
    row = (
        await db.execute(
            select(Quote).where(Quote.id == quote_id, Quote.project_id == project_id)
        )
    ).scalar_one_or_none()
    if row is None or (
        access.project.active_revision_id is not None
        and row.manuscript_revision_id not in (None, access.project.active_revision_id)
    ):
        raise HTTPException(status_code=404, detail="Quotation not found")
    source = (
        await db.execute(
            select(Source).where(
                Source.id == row.source_id,
                Source.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if body.verified and (source is None or not source.verified):
        raise HTTPException(
            status_code=409,
            detail="Verify the source record before verifying an exact quotation.",
        )
    now = datetime.now(timezone.utc)
    row.verified = body.verified
    row.verify_note = body.note
    row.verification_method = body.method
    row.verified_by = current_user.id if body.verified else None
    row.verified_at = now if body.verified else None
    db.add(
        Event(
            project_id=project_id,
            user_id=current_user.id,
            kind="collaboration_quote_verification_changed",
            data={
                "quote_id": str(row.id),
                "source_id": str(row.source_id),
                "verified": row.verified,
                "method": body.method,
                "document_version": access.project.document_version,
            },
        )
    )
    await db.commit()
    return {
        "id": row.id,
        "source_id": row.source_id,
        "verified": row.verified,
        "verification_method": row.verification_method,
        "verified_by": row.verified_by,
        "verified_at": row.verified_at,
    }
