"""Out-of-order replay protection for customer and invoice webhooks.

Subscriptions were already order-safe via last_event_at; customers and invoices
were not, so a replayed-but-stale customer.updated / invoice.updated could
overwrite newer state or totals. These tests lock in the new guards.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commercial.billing import ingest_webhook
from app.core.config import get_settings
from app.models.commercial import BillingCustomer, Invoice


def _signed_event(envelope: dict) -> tuple[bytes, str]:
    raw = json.dumps(envelope, separators=(",", ":")).encode()
    timestamp = int(datetime.now(timezone.utc).timestamp())
    digest = hmac.new(
        get_settings().BILLING_WEBHOOK_SECRET.encode(),
        f"{timestamp}.".encode() + raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, f"t={timestamp},v1={digest}"


async def _send(db: AsyncSession, envelope: dict):
    raw, signature = _signed_event(envelope)
    event, _created = await ingest_webhook(db, "test", raw, signature)
    return event


async def test_stale_customer_event_is_ignored(db_session: AsyncSession, test_institution) -> None:
    customer_id = f"cus_{uuid4().hex}"
    newer = datetime.now(timezone.utc)
    older = newer - timedelta(minutes=5)

    fresh = await _send(
        db_session,
        {
            "id": f"evt_{uuid4().hex}",
            "type": "customer.updated",
            "occurred_at": newer.isoformat(),
            "data": {
                "customer_id": customer_id,
                "institution_id": str(test_institution.id),
                "state": "suspended",
            },
        },
    )
    assert fresh.state == "processed"

    stale = await _send(
        db_session,
        {
            "id": f"evt_{uuid4().hex}",
            "type": "customer.updated",
            "occurred_at": older.isoformat(),
            "data": {
                "customer_id": customer_id,
                "institution_id": str(test_institution.id),
                "state": "active",
            },
        },
    )
    assert stale.state == "ignored_out_of_order"

    row = (
        await db_session.execute(
            select(BillingCustomer).where(BillingCustomer.external_customer_id == customer_id)
        )
    ).scalar_one()
    assert row.state == "suspended"  # newer state preserved, stale replay ignored


async def test_stale_invoice_event_is_ignored(db_session: AsyncSession, test_institution) -> None:
    customer_id = f"cus_{uuid4().hex}"
    invoice_id = f"inv_{uuid4().hex}"
    newer = datetime.now(timezone.utc)
    older = newer - timedelta(minutes=5)

    fresh = await _send(
        db_session,
        {
            "id": f"evt_{uuid4().hex}",
            "type": "invoice.updated",
            "occurred_at": newer.isoformat(),
            "data": {
                "customer_id": customer_id,
                "institution_id": str(test_institution.id),
                "invoice_id": invoice_id,
                "state": "paid",
                "currency": "INR",
                "total_minor": 5000,
            },
        },
    )
    assert fresh.state == "processed"

    stale = await _send(
        db_session,
        {
            "id": f"evt_{uuid4().hex}",
            "type": "invoice.updated",
            "occurred_at": older.isoformat(),
            "data": {
                "customer_id": customer_id,
                "institution_id": str(test_institution.id),
                "invoice_id": invoice_id,
                "state": "open",
                "currency": "INR",
                "total_minor": 1,
            },
        },
    )
    assert stale.state == "ignored_out_of_order"

    row = (
        await db_session.execute(
            select(Invoice).where(Invoice.external_invoice_id == invoice_id)
        )
    ).scalar_one()
    assert row.total_minor == 5000  # newer totals preserved
    assert row.state == "paid"
