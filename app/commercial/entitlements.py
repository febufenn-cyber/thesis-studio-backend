"""Backend-enforced editions, entitlements and usage accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.commercial import (
    BillingCustomer,
    EditionVersion,
    EntitlementGrant,
    Subscription,
    UsageLedgerEntry,
)


class EntitlementDenied(RuntimeError):
    """The requested commercial capability is not enabled."""


class EntitlementQuotaExceeded(RuntimeError):
    """A metered entitlement has exhausted its current period allowance."""


# Production accounts without a contract remain deliberately conservative.
FALLBACK_ENTITLEMENTS: dict[str, Any] = {
    "project.create": True,
    "project.active_limit": 1,
    "manuscript.max_size_mb": 25,
    "ai.chat": False,
    "ai.chapter_review.monthly": 0,
    "ai.whole_thesis_review.monthly": 0,
    "export.docx": True,
    "export.pdf": False,
    "export.pdf.monthly": 0,
    "review.supervisor": False,
    "profile.custom": False,
    "seat.student_limit": 1,
    "seat.staff_limit": 0,
    "retention.days": 30,
    "support.priority": "standard",
}

# Non-production preserves the validated Phase 1–4 workflows while billing and
# procurement are being configured. This is never used in production.
PILOT_ENTITLEMENTS: dict[str, Any] = {
    "project.create": True,
    "project.active_limit": 100,
    "manuscript.max_size_mb": 100,
    "ai.chat": True,
    "ai.chapter_review.monthly": 1000,
    "ai.whole_thesis_review.monthly": 100,
    "export.docx": True,
    "export.pdf": True,
    "export.pdf.monthly": 1000,
    "review.supervisor": True,
    "profile.custom": True,
    "seat.student_limit": 1000,
    "seat.staff_limit": 1000,
    "retention.days": 365,
    "support.priority": "pilot",
}


@dataclass(frozen=True)
class EntitlementContext:
    institution_id: UUID | None
    user_id: UUID | None
    project_id: UUID | None = None


@dataclass(frozen=True)
class EntitlementDecision:
    key: str
    value: Any
    source: str
    grant_id: UUID | None
    edition_version_id: UUID | None
    consumed: Decimal
    remaining: Decimal | None
    period_key: str | None

    @property
    def enabled(self) -> bool:
        if isinstance(self.value, bool):
            return self.value
        if isinstance(self.value, (int, float, Decimal)):
            return Decimal(str(self.value)) > 0
        return self.value not in (None, "", "disabled", "none")


def period_key(period: str | None, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if period == "day":
        return now.strftime("%Y-%m-%d")
    if period == "week":
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    if period == "year":
        return now.strftime("%Y")
    return now.strftime("%Y-%m")


def _extract_value(payload: dict | None) -> Any:
    data = payload or {}
    if "value" in data:
        return data["value"]
    if "enabled" in data:
        return bool(data["enabled"])
    if "limit" in data:
        return data["limit"]
    return data


def _scope_specificity(grant: EntitlementGrant) -> int:
    if grant.project_id is not None:
        return 3
    if grant.user_id is not None:
        return 2
    if grant.institution_id is not None:
        return 1
    return 0


async def _active_edition(
    db: AsyncSession, context: EntitlementContext, now: datetime
) -> tuple[EditionVersion | None, str | None]:
    customer_predicates = []
    if context.institution_id is not None:
        customer_predicates.append(BillingCustomer.institution_id == context.institution_id)
    if context.user_id is not None:
        customer_predicates.append(BillingCustomer.user_id == context.user_id)
    if not customer_predicates:
        return None, None
    row = (
        await db.execute(
            select(EditionVersion, Subscription.access_state)
            .join(Subscription, Subscription.edition_version_id == EditionVersion.id)
            .join(BillingCustomer, BillingCustomer.id == Subscription.billing_customer_id)
            .where(
                or_(*customer_predicates),
                Subscription.access_state.in_({"active", "grace"}),
                or_(Subscription.grace_until.is_(None), Subscription.grace_until > now),
                EditionVersion.state == "published",
                or_(EditionVersion.effective_from.is_(None), EditionVersion.effective_from <= now),
                or_(EditionVersion.effective_until.is_(None), EditionVersion.effective_until > now),
            )
            .order_by(Subscription.updated_at.desc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else (None, None)


async def _matching_grants(
    db: AsyncSession, context: EntitlementContext, key: str, now: datetime
) -> list[EntitlementGrant]:
    scopes = [
        and_(
            EntitlementGrant.institution_id.is_(None),
            EntitlementGrant.user_id.is_(None),
            EntitlementGrant.project_id.is_(None),
        )
    ]
    if context.institution_id is not None:
        scopes.append(
            and_(
                EntitlementGrant.institution_id == context.institution_id,
                EntitlementGrant.user_id.is_(None),
                EntitlementGrant.project_id.is_(None),
            )
        )
    if context.user_id is not None:
        scopes.append(
            and_(
                EntitlementGrant.user_id == context.user_id,
                EntitlementGrant.project_id.is_(None),
                or_(
                    EntitlementGrant.institution_id.is_(None),
                    EntitlementGrant.institution_id == context.institution_id,
                ),
            )
        )
    if context.project_id is not None:
        scopes.append(
            and_(
                EntitlementGrant.project_id == context.project_id,
                or_(EntitlementGrant.user_id.is_(None), EntitlementGrant.user_id == context.user_id),
                or_(
                    EntitlementGrant.institution_id.is_(None),
                    EntitlementGrant.institution_id == context.institution_id,
                ),
            )
        )
    rows = list(
        (
            await db.execute(
                select(EntitlementGrant).where(
                    EntitlementGrant.key == key,
                    EntitlementGrant.state == "active",
                    or_(*scopes),
                    or_(EntitlementGrant.starts_at.is_(None), EntitlementGrant.starts_at <= now),
                    or_(EntitlementGrant.ends_at.is_(None), EntitlementGrant.ends_at > now),
                )
            )
        ).scalars()
    )
    return sorted(rows, key=lambda row: (row.priority, _scope_specificity(row), row.created_at))


async def usage_total(
    db: AsyncSession,
    context: EntitlementContext,
    key: str,
    *,
    reset_period: str = "month",
    now: datetime | None = None,
) -> tuple[Decimal, str]:
    pkey = period_key(reset_period, now)
    predicates = [
        UsageLedgerEntry.entitlement_key == key,
        UsageLedgerEntry.period_key == pkey,
    ]
    if context.institution_id is not None:
        predicates.append(UsageLedgerEntry.institution_id == context.institution_id)
    if context.user_id is not None:
        predicates.append(UsageLedgerEntry.user_id == context.user_id)
    if context.project_id is not None:
        predicates.append(UsageLedgerEntry.project_id == context.project_id)
    total = (
        await db.execute(
            select(func.coalesce(func.sum(UsageLedgerEntry.quantity), 0)).where(*predicates)
        )
    ).scalar_one()
    return Decimal(str(total)), pkey


async def resolve_entitlement(
    db: AsyncSession,
    context: EntitlementContext,
    key: str,
    *,
    reset_period: str | None = None,
    now: datetime | None = None,
) -> EntitlementDecision:
    now = now or datetime.now(timezone.utc)
    edition, access_state = await _active_edition(db, context, now)
    fallback = FALLBACK_ENTITLEMENTS if get_settings().ENV == "production" else PILOT_ENTITLEMENTS
    value: Any = fallback.get(key)
    source = "fallback" if get_settings().ENV == "production" else "pilot_grandfathered"
    edition_version_id: UUID | None = None
    grant_id: UUID | None = None
    if edition is not None and key in (edition.entitlements or {}):
        value = (edition.entitlements or {})[key]
        source = f"edition:{access_state}"
        edition_version_id = edition.id
    grants = await _matching_grants(db, context, key, now)
    if grants:
        selected = grants[-1]
        value = _extract_value(selected.value)
        source = f"grant:{selected.source}"
        grant_id = selected.id
        edition_version_id = selected.edition_version_id or edition_version_id
    consumed = Decimal(0)
    remaining: Decimal | None = None
    pkey: str | None = None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and reset_period:
        consumed, pkey = await usage_total(db, context, key, reset_period=reset_period, now=now)
        remaining = max(Decimal(0), Decimal(str(value)) - consumed)
    return EntitlementDecision(
        key=key,
        value=value,
        source=source,
        grant_id=grant_id,
        edition_version_id=edition_version_id,
        consumed=consumed,
        remaining=remaining,
        period_key=pkey,
    )


async def require_entitlement(
    db: AsyncSession,
    context: EntitlementContext,
    key: str,
    *,
    quantity: Decimal | int | float = 1,
    reset_period: str | None = None,
) -> EntitlementDecision:
    decision = await resolve_entitlement(db, context, key, reset_period=reset_period)
    if not decision.enabled:
        raise EntitlementDenied(f"{key} is not included in the current edition or contract.")
    if decision.remaining is not None and decision.remaining < Decimal(str(quantity)):
        raise EntitlementQuotaExceeded(
            f"{key} allowance is exhausted for {decision.period_key}; contact the account administrator or wait for the next period."
        )
    return decision


async def record_usage(
    db: AsyncSession,
    context: EntitlementContext,
    key: str,
    operation: str,
    *,
    quantity: Decimal | int | float = 1,
    unit: str = "operation",
    reset_period: str = "month",
    idempotency_key: str | None = None,
    metadata: dict | None = None,
) -> UsageLedgerEntry:
    if idempotency_key:
        existing = (
            await db.execute(
                select(UsageLedgerEntry).where(UsageLedgerEntry.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    row = UsageLedgerEntry(
        institution_id=context.institution_id,
        user_id=context.user_id,
        project_id=context.project_id,
        entitlement_key=key,
        operation=operation,
        quantity=Decimal(str(quantity)),
        unit=unit,
        idempotency_key=idempotency_key,
        period_key=period_key(reset_period),
        metadata_json=metadata or {},
        release_sha=get_settings().RELEASE_SHA or None,
    )
    db.add(row)
    await db.flush()
    return row


async def grant_entitlement(
    db: AsyncSession,
    context: EntitlementContext,
    key: str,
    value: Any,
    *,
    source: str,
    granted_by: UUID | None,
    source_reference: str | None = None,
    reason: str | None = None,
    priority: int = 100,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    edition_version_id: UUID | None = None,
) -> EntitlementGrant:
    row = EntitlementGrant(
        key=key,
        institution_id=context.institution_id,
        user_id=context.user_id,
        project_id=context.project_id,
        edition_version_id=edition_version_id,
        source=source,
        source_reference=source_reference,
        value={"value": value},
        priority=priority,
        starts_at=starts_at,
        ends_at=ends_at,
        granted_by=granted_by,
        reason=reason,
    )
    db.add(row)
    await db.flush()
    return row
