"""Persist advisory quote-verification results (docs/LLD.md 3.3).

Verifies a quote against provided source bytes (extracted by MIME type) and
upserts a ``QuoteVerification`` row. Never sets ``Quote.verified``; a missing or
unreadable source yields ``unverifiable``, never ``verified``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quote import Quote
from app.models.quote_verification import QuoteVerification
from app.verification.extractors.base import ExtractorError
from app.verification.extractors.registry import get_extractor
from app.verification.quotes import verify_against_doc


async def _upsert(
    db: AsyncSession,
    quote: Quote,
    *,
    kind: str,
    status: str,
    score: float | None,
    method: str,
    matched_locator: str | None,
    detail: dict,
) -> QuoteVerification:
    row = (
        await db.execute(
            select(QuoteVerification).where(
                QuoteVerification.quote_id == quote.id, QuoteVerification.kind == kind
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = QuoteVerification(
            quote_id=quote.id,
            source_id=quote.source_id,
            project_id=quote.project_id,
            user_id=quote.user_id,
            kind=kind,
        )
        db.add(row)
    row.status = status
    row.score = score
    row.method = method
    row.matched_locator = matched_locator
    row.detail = detail
    await db.flush()
    return row


async def verify_quote_against_source(
    db: AsyncSession,
    quote: Quote,
    *,
    source_bytes: bytes | None,
    mime_type: str,
) -> QuoteVerification:
    """Verify a quote against source bytes and persist the result (advisory)."""
    if not source_bytes:
        return await _upsert(
            db, quote, kind="verbatim", status="unverifiable", score=None,
            method="none", matched_locator=None,
            detail={"reason": "no source artifact available"},
        )
    try:
        extractor = get_extractor(mime_type)
        doc = extractor.extract(source_bytes)
    except ExtractorError as exc:
        return await _upsert(
            db, quote, kind="verbatim", status="unverifiable", score=None,
            method="none", matched_locator=None, detail={"reason": str(exc)},
        )

    result, findings = verify_against_doc(quote.text, quote.page_or_loc, doc)
    return await _upsert(
        db, quote, kind="verbatim", status=result.status, score=result.score,
        method=result.method, matched_locator=result.matched_locator,
        detail={
            "snippet": result.snippet[:400],
            "extractor": doc.extractor,
            "findings": [
                {"rule": f.rule, "severity": f.severity, **f.detail} for f in findings
            ],
        },
    )


async def verification_report(db: AsyncSession, project_id) -> list[QuoteVerification]:
    """All verification rows for a project."""
    return list(
        (
            await db.execute(
                select(QuoteVerification)
                .where(QuoteVerification.project_id == project_id)
                .order_by(QuoteVerification.checked_at.desc())
            )
        ).scalars()
    )
