"""Phase 5 billing, entitlement and revocable-session API tests."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commercial.sessions import issue_session
from app.core.config import get_settings
from app.models.commercial import EditionVersion, ProductEdition, Subscription
from app.models.tenancy import OrganizationMembership
from app.models.user import User


pytestmark = pytest.mark.asyncio


async def _admin_session(db: AsyncSession, institution, user: User) -> dict[str, str]:
    db.add(
        OrganizationMembership(
            institution_id=institution.id,
            user_id=user.id,
            role="institution_admin",
            affiliation_status="admin_verified",
            status="active",
            verified_by=user.id,
            verified_at=datetime.now(timezone.utc),
        )
    )
    _, token = await issue_session(db, user, auth_method="test")
    await db.commit()
    return {get_settings().SESSION_COOKIE_NAME: token}


def _signature(raw: bytes) -> str:
    timestamp = int(datetime.now(timezone.utc).timestamp())
    digest = hmac.new(
        get_settings().BILLING_WEBHOOK_SECRET.encode(),
        f"{timestamp}.".encode() + raw,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


async def test_signed_billing_event_is_idempotent_and_provisions_access(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution,
    user_a: User,
) -> None:
    edition = ProductEdition(
        slug=f"institution-{uuid4().hex[:8]}",
        audience="institution",
        name="Institution Annual",
        state="published",
    )
    db_session.add(edition)
    await db_session.flush()
    version = EditionVersion(
        edition_id=edition.id,
        version=1,
        label="Annual 2026",
        currency="INR",
        billing_interval="year",
        list_price_minor=100000,
        entitlements={
            "project.create": True,
            "project.active_limit": 100,
            "ai.chat": True,
            "export.pdf": True,
            "export.pdf.monthly": 1000,
            "review.supervisor": True,
        },
        state="published",
        effective_from=datetime.now(timezone.utc),
        created_by=user_a.id,
        published_by=user_a.id,
        published_at=datetime.now(timezone.utc),
    )
    db_session.add(version)
    await db_session.commit()

    envelope = {
        "id": f"evt_{uuid4().hex}",
        "type": "subscription.updated",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "customer_id": f"cus_{uuid4().hex}",
            "subscription_id": f"sub_{uuid4().hex}",
            "institution_id": str(test_institution.id),
            "actor_user_id": str(user_a.id),
            "edition_slug": edition.slug,
            "edition_version": 1,
            "state": "active",
            "current_period_start": datetime.now(timezone.utc).isoformat(),
            "current_period_end": datetime(2027, 7, 12, tzinfo=timezone.utc).isoformat(),
        },
    }
    raw = json.dumps(envelope, separators=(",", ":")).encode()
    headers = {"X-Billing-Signature": _signature(raw), "Content-Type": "application/json"}
    first = await client.post("/billing/webhooks/test", content=raw, headers=headers)
    assert first.status_code == 200
    assert first.json()["created"] is True
    second = await client.post("/billing/webhooks/test", content=raw, headers=headers)
    assert second.status_code == 200
    assert second.json()["created"] is False
    subscription = (await db_session.execute(select(Subscription))).scalar_one()
    assert subscription.access_state == "active"
    assert subscription.edition_version_id == version.id


async def test_admin_can_grant_entitlement_after_recent_reauthentication(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution,
    user_a: User,
) -> None:
    cookies = await _admin_session(db_session, test_institution, user_a)
    response = await client.post(
        f"/institutions/{test_institution.id}/commercial/entitlement-grants",
        cookies=cookies,
        json={
            "key": "export.pdf",
            "value": True,
            "source_reference": "PO-2026-001",
            "reason": "Annual institutional procurement contract.",
            "priority": 500,
        },
    )
    assert response.status_code == 201
    summary = await client.get(
        f"/institutions/{test_institution.id}/commercial/entitlements",
        cookies=cookies,
    )
    assert summary.status_code == 200
    pdf = next(row for row in summary.json()["entitlements"] if row["key"] == "export.pdf")
    assert pdf["value"] is True
    assert pdf["source"] == "grant:manual_contract"


async def test_user_can_revoke_all_device_sessions(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution,
    user_a: User,
) -> None:
    _, token = await issue_session(db_session, user_a, auth_method="test")
    await db_session.commit()
    cookies = {get_settings().SESSION_COOKIE_NAME: token}
    listing = await client.get("/auth/sessions", cookies=cookies)
    assert listing.status_code == 200
    assert any(row["current"] for row in listing.json())
    revoked = await client.post(
        "/auth/sessions/revoke-all",
        cookies=cookies,
        json={"keep_current": False, "reason": "Lost device response."},
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] >= 1
    denied = await client.get("/auth/me", cookies=cookies)
    assert denied.status_code == 401
