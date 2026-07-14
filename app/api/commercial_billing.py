"""Commercial editions, entitlements, usage and verified billing webhooks."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentApplicationSession, CurrentUser
from app.collaboration.capabilities import require_institution_capability
from app.commercial.billing import BillingEventError, BillingSignatureError, ingest_webhook, replay_event
from app.commercial.entitlements import EntitlementContext, grant_entitlement, resolve_entitlement
from app.commercial.sessions import require_recent_reauthentication
from app.db.deps import get_db
from app.models.commercial import (
    BillingCustomer,
    BillingEvent,
    CostLedgerEntry,
    EntitlementDefinition,
    EntitlementGrant,
    Subscription,
    TenantBudget,
    UsageLedgerEntry,
)


router = APIRouter(tags=["commercial"])


class EntitlementGrantCreate(BaseModel):
    key: str = Field(..., min_length=2, max_length=120)
    value: Any
    source_reference: str | None = Field(None, max_length=240)
    reason: str = Field(..., min_length=5, max_length=2000)
    priority: int = Field(100, ge=0, le=10000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    user_id: UUID | None = None
    project_id: UUID | None = None


class TenantBudgetCreate(BaseModel):
    category: str = Field(..., min_length=2, max_length=50)
    period: str = Field("month", pattern=r"^(day|week|month|year)$")
    soft_limit: Decimal | None = Field(None, ge=0)
    hard_limit: Decimal | None = Field(None, ge=0)
    unit: str = Field(..., min_length=1, max_length=40)
    currency: str | None = Field(None, min_length=3, max_length=3)
    grace_ratio: Decimal = Field(0, ge=0, le=1)
    override_until: datetime | None = None


def _billing_event_institution_id(row: BillingEvent) -> UUID | None:
    """Return the tenant bound by the verified billing envelope."""
    data = dict((row.payload or {}).get("data") or {})
    value = data.get("institution_id")
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


@router.post("/billing/webhooks/{provider}")
async def billing_webhook(
    provider: str,
    request: Request,
    x_billing_signature: str = Header(..., alias="X-Billing-Signature"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    raw = await request.body()
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=413, detail="Billing event exceeds the accepted size.")
    try:
        event, created = await ingest_webhook(db, provider[:40], raw, x_billing_signature)
    except BillingSignatureError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BillingEventError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "received": True,
        "created": created,
        "event_id": event.id,
        "state": event.state,
    }


@router.get("/institutions/{institution_id}/commercial/entitlements")
async def institution_entitlements(
    institution_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "entitlement.read")
    definitions = list((await db.execute(select(EntitlementDefinition).order_by(EntitlementDefinition.key))).scalars())
    decisions = []
    for definition in definitions:
        decision = await resolve_entitlement(
            db,
            EntitlementContext(institution_id=institution_id, user_id=None),
            definition.key,
            reset_period=definition.reset_period,
        )
        decisions.append(
            {
                "key": definition.key,
                "description": definition.description,
                "unit": definition.unit,
                "value": decision.value,
                "source": decision.source,
                "consumed": decision.consumed,
                "remaining": decision.remaining,
                "period_key": decision.period_key,
            }
        )
    return {"institution_id": institution_id, "entitlements": decisions}


@router.post("/institutions/{institution_id}/commercial/entitlement-grants", status_code=201)
async def create_manual_grant(
    institution_id: UUID,
    body: EntitlementGrantCreate,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "entitlement.manage")
    await require_recent_reauthentication(current_session)
    definition = (
        await db.execute(select(EntitlementDefinition).where(EntitlementDefinition.key == body.key))
    ).scalar_one_or_none()
    if definition is None:
        raise HTTPException(status_code=422, detail="Unknown entitlement key")
    if body.ends_at and body.starts_at and body.ends_at <= body.starts_at:
        raise HTTPException(status_code=422, detail="Grant end must be after its start.")
    row = await grant_entitlement(
        db,
        EntitlementContext(
            institution_id=institution_id,
            user_id=body.user_id,
            project_id=body.project_id,
        ),
        body.key,
        body.value,
        source="manual_contract",
        source_reference=body.source_reference,
        reason=body.reason,
        priority=body.priority,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        granted_by=current_user.id,
    )
    await db.commit()
    await db.refresh(row)
    return {
        "id": row.id,
        "key": row.key,
        "value": row.value,
        "state": row.state,
        "source": row.source,
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
    }


@router.delete("/institutions/{institution_id}/commercial/entitlement-grants/{grant_id}")
async def revoke_manual_grant(
    institution_id: UUID,
    grant_id: UUID,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "entitlement.manage")
    await require_recent_reauthentication(current_session)
    row = (
        await db.execute(
            select(EntitlementGrant).where(
                EntitlementGrant.id == grant_id,
                EntitlementGrant.institution_id == institution_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Entitlement grant not found")
    row.state = "revoked"
    row.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": row.id, "state": row.state, "revoked_at": row.revoked_at}


@router.get("/institutions/{institution_id}/commercial/billing")
async def billing_summary(
    institution_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "billing.read")
    customers = list(
        (await db.execute(select(BillingCustomer).where(BillingCustomer.institution_id == institution_id))).scalars()
    )
    customer_ids = [row.id for row in customers]
    subscriptions = list(
        (await db.execute(select(Subscription).where(Subscription.billing_customer_id.in_(customer_ids)))).scalars()
    ) if customer_ids else []
    recent_events = list(
        (
            await db.execute(
                select(BillingEvent)
                .order_by(BillingEvent.created_at.desc())
                .limit(500)
            )
        ).scalars()
    )
    events = [row for row in recent_events if _billing_event_institution_id(row) == institution_id][:100]
    return {
        "institution_id": institution_id,
        "customers": [
            {"id": row.id, "provider": row.provider, "state": row.state, "created_at": row.created_at}
            for row in customers
        ],
        "subscriptions": [
            {
                "id": row.id,
                "provider": row.provider,
                "state": row.state,
                "access_state": row.access_state,
                "current_period_end": row.current_period_end,
                "grace_until": row.grace_until,
                "cancel_at_period_end": row.cancel_at_period_end,
            }
            for row in subscriptions
        ],
        "recent_event_failures": [
            {"id": row.id, "provider": row.provider, "event_type": row.event_type, "state": row.state, "attempts": row.attempts, "created_at": row.created_at}
            for row in events if row.state == "failed"
        ],
    }


@router.post("/institutions/{institution_id}/commercial/billing-events/{event_id}/replay")
async def replay_billing_event(
    institution_id: UUID,
    event_id: UUID,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "billing.manage")
    await require_recent_reauthentication(current_session)
    event = (
        await db.execute(select(BillingEvent).where(BillingEvent.id == event_id))
    ).scalar_one_or_none()
    if event is None or _billing_event_institution_id(event) != institution_id:
        raise HTTPException(status_code=404, detail="Billing event not found")
    try:
        row = await replay_event(db, event_id)
    except BillingEventError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": row.id, "state": row.state, "attempts": row.attempts, "processed_at": row.processed_at}


@router.get("/institutions/{institution_id}/commercial/usage")
async def usage_summary(
    institution_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "usage.read_aggregate")
    usage = list(
        (
            await db.execute(
                select(
                    UsageLedgerEntry.entitlement_key,
                    UsageLedgerEntry.period_key,
                    func.sum(UsageLedgerEntry.quantity),
                )
                .where(UsageLedgerEntry.institution_id == institution_id)
                .group_by(UsageLedgerEntry.entitlement_key, UsageLedgerEntry.period_key)
                .order_by(UsageLedgerEntry.period_key.desc(), UsageLedgerEntry.entitlement_key)
            )
        ).all()
    )
    costs = list(
        (
            await db.execute(
                select(CostLedgerEntry.category, CostLedgerEntry.currency, func.sum(CostLedgerEntry.estimated_cost_minor))
                .where(CostLedgerEntry.institution_id == institution_id)
                .group_by(CostLedgerEntry.category, CostLedgerEntry.currency)
            )
        ).all()
    )
    return {
        "institution_id": institution_id,
        "usage": [{"key": key, "period": period, "quantity": quantity} for key, period, quantity in usage],
        "estimated_costs": [{"category": category, "currency": currency, "minor_units": total} for category, currency, total in costs],
        "content_analytics_performed": False,
    }


@router.put("/institutions/{institution_id}/commercial/budgets/{category}")
async def set_tenant_budget(
    institution_id: UUID,
    category: str,
    body: TenantBudgetCreate,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "budget.manage")
    await require_recent_reauthentication(current_session)
    if category != body.category:
        raise HTTPException(status_code=422, detail="Budget category path and body must match.")
    row = (
        await db.execute(
            select(TenantBudget).where(
                TenantBudget.institution_id == institution_id,
                TenantBudget.category == category,
                TenantBudget.period == body.period,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = TenantBudget(institution_id=institution_id, category=category, period=body.period, unit=body.unit, created_by=current_user.id)
        db.add(row)
    row.soft_limit = body.soft_limit
    row.hard_limit = body.hard_limit
    row.unit = body.unit
    row.currency = body.currency.upper() if body.currency else None
    row.grace_ratio = body.grace_ratio
    row.override_until = body.override_until
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "category": row.category, "period": row.period, "soft_limit": row.soft_limit, "hard_limit": row.hard_limit, "unit": row.unit, "override_until": row.override_until}
