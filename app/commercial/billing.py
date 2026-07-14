"""Provider-neutral billing ingestion with signature verification and replay."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.commercial import (
    BillingCustomer,
    BillingEvent,
    EditionVersion,
    Invoice,
    Payment,
    ProductEdition,
    Subscription,
)
from app.models.event import Event


class BillingSignatureError(RuntimeError):
    pass


class BillingEventError(RuntimeError):
    pass


_ACCESS_STATE = {
    "trialing": "active",
    "active": "active",
    "past_due": "grace",
    "incomplete": "pending",
    "incomplete_expired": "disabled",
    "unpaid": "disabled",
    "cancelled": "disabled",
    "canceled": "disabled",
    "paused": "disabled",
}


def verify_webhook_signature(raw_body: bytes, signature_header: str, secret: str) -> int:
    """Verify ``t=<unix>,v1=<hex>`` HMAC-SHA256 signatures.

    The provider adapter may translate a native provider signature into this canonical
    envelope before calling the service. Raw events are retained for replay, while
    secrets and headers are never persisted.
    """

    if not secret:
        raise BillingSignatureError("Billing webhook verification is not configured.")
    values: dict[str, str] = {}
    for part in signature_header.split(","):
        key, _, value = part.strip().partition("=")
        if key and value:
            values[key] = value
    if "t" not in values or "v1" not in values:
        raise BillingSignatureError("Malformed billing signature.")
    try:
        timestamp = int(values["t"])
    except ValueError as exc:
        raise BillingSignatureError("Malformed billing timestamp.") from exc
    settings = get_settings()
    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - timestamp) > settings.BILLING_WEBHOOK_TOLERANCE_SECONDS:
        raise BillingSignatureError("Billing event timestamp is outside the accepted window.")
    expected = hmac.new(
        secret.encode("utf-8"),
        str(timestamp).encode("ascii") + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, values["v1"]):
        raise BillingSignatureError("Billing webhook signature verification failed.")
    return timestamp


def parse_envelope(raw_body: bytes) -> dict[str, Any]:
    try:
        envelope = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BillingEventError("Billing event is not valid JSON.") from exc
    required = {"id", "type", "occurred_at", "data"}
    missing = sorted(required - set(envelope))
    if missing:
        raise BillingEventError(f"Billing event is missing: {', '.join(missing)}")
    if not isinstance(envelope["data"], dict):
        raise BillingEventError("Billing event data must be an object.")
    return envelope


def _event_time(value: str | int | float | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


async def store_event(
    db: AsyncSession,
    provider: str,
    envelope: dict[str, Any],
    raw_body: bytes,
    *,
    signature_verified: bool,
) -> tuple[BillingEvent, bool]:
    existing = (
        await db.execute(
            select(BillingEvent).where(
                BillingEvent.provider == provider,
                BillingEvent.external_event_id == str(envelope["id"]),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    row = BillingEvent(
        provider=provider,
        external_event_id=str(envelope["id"]),
        event_type=str(envelope["type"]),
        payload_hash=hashlib.sha256(raw_body).hexdigest(),
        payload=envelope,
        signature_verified=signature_verified,
        occurred_at=_event_time(envelope["occurred_at"]),
    )
    db.add(row)
    await db.flush()
    return row, True


async def _edition_version(db: AsyncSession, data: dict[str, Any]) -> EditionVersion | None:
    edition_slug = data.get("edition_slug")
    version = data.get("edition_version")
    if not edition_slug:
        return None
    query = (
        select(EditionVersion)
        .join(ProductEdition, ProductEdition.id == EditionVersion.edition_id)
        .where(ProductEdition.slug == str(edition_slug), EditionVersion.state == "published")
    )
    if version is not None:
        query = query.where(EditionVersion.version == int(version))
    else:
        query = query.order_by(EditionVersion.version.desc()).limit(1)
    return (await db.execute(query)).scalar_one_or_none()


async def _customer(db: AsyncSession, provider: str, data: dict[str, Any]) -> BillingCustomer:
    external_id = str(data.get("customer_id") or "")
    if not external_id:
        raise BillingEventError("Billing event lacks customer_id.")
    row = (
        await db.execute(
            select(BillingCustomer).where(
                BillingCustomer.provider == provider,
                BillingCustomer.external_customer_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        institution_id = UUID(str(data["institution_id"])) if data.get("institution_id") else None
        user_id = UUID(str(data["user_id"])) if data.get("user_id") else None
        if institution_id is None and user_id is None:
            raise BillingEventError("A billing customer must bind to an institution or user.")
        row = BillingCustomer(
            provider=provider,
            external_customer_id=external_id,
            institution_id=institution_id,
            user_id=user_id,
            billing_email_hash=data.get("billing_email_hash"),
            metadata_json=dict(data.get("customer_metadata") or {}),
        )
        db.add(row)
        await db.flush()
    return row


async def _process_customer(
    db: AsyncSession, provider: str, event: BillingEvent, data: dict[str, Any]
) -> BillingCustomer:
    row = await _customer(db, provider, data)
    # Ignore stale replays: a customer.* event older than the last applied one
    # must not overwrite newer state (mirrors the subscription ordering guard).
    if row.last_event_at is not None and event.occurred_at < row.last_event_at:
        event.state = "ignored_out_of_order"
        return row
    row.state = str(data.get("state") or row.state)
    row.metadata_json = {**(row.metadata_json or {}), **dict(data.get("customer_metadata") or {})}
    row.last_event_at = event.occurred_at
    return row


async def _process_subscription(
    db: AsyncSession,
    provider: str,
    event: BillingEvent,
    data: dict[str, Any],
) -> Subscription:
    customer = await _customer(db, provider, data)
    external_id = str(data.get("subscription_id") or "")
    if not external_id:
        raise BillingEventError("Subscription event lacks subscription_id.")
    row = (
        await db.execute(
            select(Subscription).where(
                Subscription.provider == provider,
                Subscription.external_subscription_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = Subscription(
            billing_customer_id=customer.id,
            provider=provider,
            external_subscription_id=external_id,
            state="incomplete",
            access_state="pending",
        )
        db.add(row)
        await db.flush()
    if row.last_event_at is not None and event.occurred_at < row.last_event_at:
        event.state = "ignored_out_of_order"
        return row

    state = str(data.get("state") or row.state)
    row.state = state
    row.access_state = _ACCESS_STATE.get(state, "pending")
    # Resolve the edition once: the previous form awaited the JOIN query twice
    # (truth test + .id), a redundant round-trip that could also disagree with
    # itself if the published edition changed between the two awaits.
    edition_version = await _edition_version(db, data)
    row.edition_version_id = edition_version.id if edition_version else row.edition_version_id
    row.current_period_start = _event_time(data["current_period_start"]) if data.get("current_period_start") else row.current_period_start
    row.current_period_end = _event_time(data["current_period_end"]) if data.get("current_period_end") else row.current_period_end
    row.cancel_at_period_end = bool(data.get("cancel_at_period_end", row.cancel_at_period_end))
    row.last_event_at = event.occurred_at
    row.metadata_json = {**(row.metadata_json or {}), **dict(data.get("subscription_metadata") or {})}
    if row.access_state == "grace":
        row.grace_until = event.occurred_at + timedelta(days=get_settings().BILLING_GRACE_DAYS)
    elif row.access_state == "active":
        row.grace_until = None
    return row


async def _process_invoice(
    db: AsyncSession, provider: str, event: BillingEvent, data: dict[str, Any]
) -> Invoice:
    customer = await _customer(db, provider, data)
    external_id = str(data.get("invoice_id") or "")
    if not external_id:
        raise BillingEventError("Invoice event lacks invoice_id.")
    row = (
        await db.execute(
            select(Invoice).where(
                Invoice.provider == provider,
                Invoice.external_invoice_id == external_id,
            )
        )
    ).scalar_one_or_none()
    subscription = None
    if data.get("subscription_id"):
        subscription = (
            await db.execute(
                select(Subscription).where(
                    Subscription.provider == provider,
                    Subscription.external_subscription_id == str(data["subscription_id"]),
                )
            )
        ).scalar_one_or_none()
    if row is None:
        row = Invoice(
            billing_customer_id=customer.id,
            subscription_id=subscription.id if subscription else None,
            provider=provider,
            external_invoice_id=external_id,
            state=str(data.get("state") or "open"),
            currency=str(data.get("currency") or "INR").upper(),
        )
        db.add(row)
    # Ignore stale replays: an invoice.* event older than the last applied one
    # must not overwrite newer totals/state (mirrors the subscription guard).
    if row.last_event_at is not None and event.occurred_at < row.last_event_at:
        event.state = "ignored_out_of_order"
        return row
    row.state = str(data.get("state") or row.state)
    row.subtotal_minor = int(data.get("subtotal_minor") or 0)
    row.tax_minor = int(data.get("tax_minor") or 0)
    row.total_minor = int(data.get("total_minor") or 0)
    row.due_at = _event_time(data["due_at"]) if data.get("due_at") else row.due_at
    row.paid_at = _event_time(data["paid_at"]) if data.get("paid_at") else row.paid_at
    row.last_event_at = event.occurred_at
    row.metadata_json = dict(data.get("invoice_metadata") or row.metadata_json or {})
    return row


async def _process_payment(db: AsyncSession, provider: str, data: dict[str, Any]) -> Payment:
    customer = await _customer(db, provider, data)
    external_id = str(data.get("payment_id") or "")
    if not external_id:
        raise BillingEventError("Payment event lacks payment_id.")
    row = (
        await db.execute(
            select(Payment).where(
                Payment.provider == provider,
                Payment.external_payment_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    invoice = None
    if data.get("invoice_id"):
        invoice = (
            await db.execute(
                select(Invoice).where(
                    Invoice.provider == provider,
                    Invoice.external_invoice_id == str(data["invoice_id"]),
                )
            )
        ).scalar_one_or_none()
    row = Payment(
        billing_customer_id=customer.id,
        invoice_id=invoice.id if invoice else None,
        provider=provider,
        external_payment_id=external_id,
        kind=str(data.get("kind") or "payment"),
        state=str(data.get("state") or "succeeded"),
        currency=str(data.get("currency") or "INR").upper(),
        amount_minor=int(data.get("amount_minor") or 0),
        occurred_at=_event_time(data.get("payment_occurred_at") or datetime.now(timezone.utc)),
        metadata_json=dict(data.get("payment_metadata") or {}),
    )
    db.add(row)
    return row


async def process_event(db: AsyncSession, event: BillingEvent) -> BillingEvent:
    if event.state == "processed":
        return event
    event.attempts += 1
    envelope = event.payload or {}
    data = dict(envelope.get("data") or {})
    try:
        if event.event_type.startswith("customer."):
            await _process_customer(db, event.provider, event, data)
        elif event.event_type.startswith("subscription."):
            await _process_subscription(db, event.provider, event, data)
        elif event.event_type.startswith("invoice."):
            await _process_invoice(db, event.provider, event, data)
        elif event.event_type.startswith("payment.") or event.event_type.startswith("refund."):
            await _process_payment(db, event.provider, data)
        else:
            event.state = "ignored_unknown"
        if event.state == "received":
            event.state = "processed"
        event.processed_at = datetime.now(timezone.utc)
        event.error_message = None
        institution_id = data.get("institution_id")
        actor_user_id = data.get("actor_user_id")
        if actor_user_id:
            db.add(
                Event(
                    project_id=None,
                    user_id=UUID(str(actor_user_id)),
                    kind="billing_event_processed",
                    data={
                        "billing_event_id": str(event.id),
                        "provider": event.provider,
                        "event_type": event.event_type,
                        "institution_id": institution_id,
                        "state": event.state,
                    },
                )
            )
    except Exception as exc:
        event.state = "failed"
        event.error_message = str(exc)[:1000]
        raise
    return event


async def ingest_webhook(
    db: AsyncSession,
    provider: str,
    raw_body: bytes,
    signature_header: str,
) -> tuple[BillingEvent, bool]:
    verify_webhook_signature(raw_body, signature_header, get_settings().BILLING_WEBHOOK_SECRET)
    envelope = parse_envelope(raw_body)
    event, created = await store_event(
        db, provider, envelope, raw_body, signature_verified=True
    )
    if created or event.state == "failed":
        await process_event(db, event)
    await db.commit()
    await db.refresh(event)
    return event, created


async def replay_event(db: AsyncSession, event_id: UUID) -> BillingEvent:
    event = (
        await db.execute(select(BillingEvent).where(BillingEvent.id == event_id))
    ).scalar_one_or_none()
    if event is None:
        raise BillingEventError("Billing event not found.")
    event.state = "received"
    event.error_message = None
    await process_event(db, event)
    await db.commit()
    await db.refresh(event)
    return event
