"""Research-consent gate — deny by default, revocable, version-pinned."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.research_consent import ResearchConsent

SCOPES = ("revision_history", "citation_patterns", "ai_provenance", "all")


def current_terms_version() -> str:
    return getattr(get_settings(), "RESEARCH_TERMS_VERSION", "") or ""


async def has_research_consent(db: AsyncSession, user_id: UUID, scope: str) -> bool:
    """True only for an active, unrevoked grant matching the *current* terms.

    A superseded terms version, a revoked grant, or a missing row is treated as
    no consent (deny-by-default).
    """
    terms = current_terms_version()
    if not terms:
        return False
    rows = list(
        (
            await db.execute(
                select(ResearchConsent).where(
                    ResearchConsent.user_id == user_id,
                    ResearchConsent.revoked_at.is_(None),
                    ResearchConsent.terms_version == terms,
                    ResearchConsent.scope.in_((scope, "all")),
                )
            )
        ).scalars()
    )
    return bool(rows)


async def grant_research_consent(
    db: AsyncSession,
    *,
    user_id: UUID,
    scope: str,
    terms_version: str,
    granted_by: UUID | None = None,
    evidence: dict | None = None,
) -> ResearchConsent:
    consent = ResearchConsent(
        user_id=user_id,
        scope=scope,
        terms_version=terms_version,
        granted_by=granted_by or user_id,
        evidence=evidence or {},
    )
    db.add(consent)
    await db.flush()
    return consent


async def revoke_research_consent(
    db: AsyncSession, *, user_id: UUID, scope: str, revoked_by: UUID | None = None
) -> int:
    """Revoke all live grants for a (user, scope). Idempotent; returns count."""
    rows = list(
        (
            await db.execute(
                select(ResearchConsent).where(
                    ResearchConsent.user_id == user_id,
                    ResearchConsent.scope == scope,
                    ResearchConsent.revoked_at.is_(None),
                )
            )
        ).scalars()
    )
    now = datetime.now(timezone.utc)
    for row in rows:
        row.revoked_at = now
        row.revoked_by = revoked_by or user_id
    await db.flush()
    return len(rows)


async def list_consents(db: AsyncSession, user_id: UUID) -> list[ResearchConsent]:
    return list(
        (
            await db.execute(
                select(ResearchConsent)
                .where(ResearchConsent.user_id == user_id)
                .order_by(ResearchConsent.granted_at.desc())
            )
        ).scalars()
    )
