"""Quote-verification API (docs/LLD.md 3.3).

Advisory: results never change ``Quote.verified``. Owner-guarded (foreign
project/quote → 404). Source content is provided inline (text or base64) or,
when present, read from the source's stored artifact.
"""

from __future__ import annotations

import base64
import binascii
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.core.config import get_settings
from app.db.deps import get_db
from app.models.quote import Quote
from app.models.quote_verification import QuoteVerification
from app.models.source import Source
from app.references.fulltext import fetch_fulltext
from app.references.http import build_client
from app.services.quote_verification_service import (
    verification_report,
    verify_quote_against_source,
)

router = APIRouter(tags=["projects"])

_MAX_SOURCE_BYTES = 25 * 1024 * 1024  # 25 MB


class VerifyQuoteRequest(BaseModel):
    source_text: str | None = None
    source_content_base64: str | None = None
    mime_type: str = "text/plain"
    run_alignment: bool = False


def _result_dict(row: QuoteVerification) -> dict:
    return {
        "quote_id": str(row.quote_id),
        "kind": row.kind,
        "status": row.status,
        "score": row.score,
        "method": row.method,
        "matched_locator": row.matched_locator,
        "detail": row.detail,
        "advisory": True,
        "checked_at": row.checked_at.isoformat() if row.checked_at else None,
    }


@router.post("/projects/{project_id}/quotes/{quote_id}/verify-source")
async def verify_quote_source(
    project_id: UUID,
    quote_id: UUID,
    body: VerifyQuoteRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify a quote against source content; advisory, never sets verified."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    quote = (
        await db.execute(
            select(Quote).where(Quote.id == quote_id, Quote.project_id == project.id)
        )
    ).scalar_one_or_none()
    if quote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found.")

    source_bytes: bytes | None = None
    mime = body.mime_type
    if body.source_text is not None:
        source_bytes = body.source_text.encode("utf-8")
        mime = "text/plain"
    elif body.source_content_base64:
        try:
            source_bytes = base64.b64decode(body.source_content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base64 source content."
            ) from exc
    if source_bytes is not None and len(source_bytes) > _MAX_SOURCE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Source content exceeds the 25 MB limit.",
        )

    row = await verify_quote_against_source(
        db, quote, source_bytes=source_bytes, mime_type=mime, run_alignment=body.run_alignment
    )
    await db.commit()
    return _result_dict(row)


@router.post("/projects/{project_id}/quotes/{quote_id}/verify-auto")
async def verify_quote_auto(
    project_id: UUID,
    quote_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch open-access full text for the quote's source and verify against it.

    Enterprise E4: no upload needed. Advisory; if no OA full text is found the
    result is ``unverifiable`` (fail-closed), never ``verified``.
    """
    project = await fetch_owned_project(db, project_id, current_user.id)
    quote = (
        await db.execute(
            select(Quote).where(Quote.id == quote_id, Quote.project_id == project.id)
        )
    ).scalar_one_or_none()
    if quote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found.")

    source_bytes: bytes | None = None
    provider: str | None = None
    if getattr(get_settings(), "FULLTEXT_ENABLED", True):
        source = (
            await db.execute(select(Source).where(Source.id == quote.source_id))
        ).scalar_one_or_none()
        doi = ""
        if source is not None:
            fields = source.fields or {}
            doi = str(fields.get("doi_or_url") or (source.identifiers or {}).get("doi") or "").strip()
        if doi:
            client = build_client()
            try:
                found = await fetch_fulltext(client, doi)
            finally:
                await client.aclose()
            if found:
                source_bytes = found["text"].encode("utf-8")
                provider = found["provider"]

    row = await verify_quote_against_source(db, quote, source_bytes=source_bytes, mime_type="text/plain")
    await db.commit()
    return {**_result_dict(row), "fulltext_provider": provider}


@router.get("/projects/{project_id}/quote-verification/report")
async def quote_verification_report(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """All advisory quote-verification results for the project."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    rows = await verification_report(db, project.id)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {"advisory": True, "counts": counts, "results": [_result_dict(r) for r in rows]}
