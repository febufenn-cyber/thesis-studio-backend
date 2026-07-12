"""Phase 5 commercial, security and release invariants."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.commercial.billing import BillingSignatureError, verify_webhook_signature
from app.commercial.entitlements import EntitlementContext, resolve_entitlement
from app.commercial.features import feature_enabled
from app.commercial.observability import opaque_identifier, release_identity
from app.commercial.recovery import canonical_digest
from app.models.commercial import EntitlementGrant, FeatureFlag, RolloutAssignment
from app.models.project import Project
from app.models.user import User


pytestmark = pytest.mark.asyncio


def test_billing_signature_is_timestamped_and_constant_time(monkeypatch) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    body = json.dumps({"id": "evt_1", "type": "customer.updated", "occurred_at": now, "data": {}}).encode()
    secret = "phase5-webhook-test-secret"
    signature = hmac.new(secret.encode(), f"{now}.".encode() + body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, f"t={now},v1={signature}", secret) == now
    with pytest.raises(BillingSignatureError):
        verify_webhook_signature(body, f"t={now},v1={'0' * 64}", secret)


def test_release_and_log_identity_are_safe() -> None:
    release = release_identity()
    assert release["schema_version"] == "0018"
    assert "JWT" not in json.dumps(release)
    assert opaque_identifier("student@example.edu") != "student@example.edu"
    assert len(opaque_identifier("student@example.edu")) == 16


def test_canonical_digest_is_stable() -> None:
    assert canonical_digest({"b": 2, "a": 1}) == canonical_digest({"a": 1, "b": 2})


async def test_scope_specific_entitlement_grant_wins(
    db_session: AsyncSession,
    user_a: User,
    test_institution,
) -> None:
    project = Project(
        user_id=user_a.id,
        institution_id=test_institution.id,
        title="Entitlement scope test",
    )
    db_session.add(project)
    await db_session.flush()
    db_session.add_all(
        [
            EntitlementGrant(
                key="export.pdf",
                institution_id=test_institution.id,
                source="manual_contract",
                value={"value": False},
                priority=100,
                granted_by=user_a.id,
            ),
            EntitlementGrant(
                key="export.pdf",
                institution_id=test_institution.id,
                user_id=user_a.id,
                project_id=project.id,
                source="temporary_override",
                value={"value": True},
                priority=100,
                starts_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                ends_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                granted_by=user_a.id,
            ),
        ]
    )
    await db_session.commit()
    decision = await resolve_entitlement(
        db_session,
        EntitlementContext(
            institution_id=test_institution.id,
            user_id=user_a.id,
            project_id=project.id,
        ),
        "export.pdf",
    )
    assert decision.value is True
    assert decision.source == "grant:temporary_override"


async def test_feature_rollout_prefers_user_over_tenant(
    db_session: AsyncSession,
    user_a: User,
    test_institution,
) -> None:
    flag = FeatureFlag(
        key=f"phase5-test-{uuid4().hex}",
        description="Progressive delivery test",
        default_enabled=False,
        created_by=user_a.id,
    )
    db_session.add(flag)
    await db_session.flush()
    db_session.add_all(
        [
            RolloutAssignment(
                feature_flag_id=flag.id,
                institution_id=test_institution.id,
                enabled=True,
                reason="Canary institution",
                created_by=user_a.id,
            ),
            RolloutAssignment(
                feature_flag_id=flag.id,
                institution_id=test_institution.id,
                user_id=user_a.id,
                enabled=False,
                reason="User holdback",
                created_by=user_a.id,
            ),
        ]
    )
    await db_session.commit()
    assert await feature_enabled(
        db_session,
        flag.key,
        institution_id=test_institution.id,
        user_id=user_a.id,
    ) is False
    assert await feature_enabled(
        db_session,
        flag.key,
        institution_id=test_institution.id,
        user_id=uuid4(),
    ) is True
