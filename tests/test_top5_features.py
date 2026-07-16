"""Top-5 launch features: triage ordering, digests, ops wiring."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.review_item import ReviewItem
from app.services.digest_service import compose_digest
from app.services.review_service import SEVERITY_RANK

pytestmark = pytest.mark.asyncio


async def test_triage_orders_blockers_then_warnings_then_info(db_session, user_a) -> None:
    """Severity ranks by meaning, not by the strings' alphabetical accident."""
    from app.models.project import Project

    project = Project(user_id=user_a.id, title="Triage", meta={}, front_matter=[],
                      chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    for sev in ("info", "block", "warn"):
        db_session.add(ReviewItem(
            project_id=project.id, user_id=user_a.id, rule=f"r_{sev}",
            fingerprint=f"f_{sev}_{uuid4().hex[:8]}", category="citations",
            severity=sev, status="open", title=sev, explanation="x",
            why_it_matters="y", location={}, evidence={}, first_seen_version=1, last_seen_version=1,
        ))
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(ReviewItem)
            .where(ReviewItem.project_id == project.id)
            .order_by(ReviewItem.status.asc(), SEVERITY_RANK, ReviewItem.created_at.asc())
        )
    ).scalars().all()
    assert [r.severity for r in rows] == ["block", "warn", "info"]


def _n(kind: str, title: str, body: str = "secret prose") -> SimpleNamespace:
    return SimpleNamespace(kind=kind, title=title, body=body)


def _pref(kind: str, email: bool, preview: bool) -> SimpleNamespace:
    return SimpleNamespace(kind=kind, email_enabled=email, content_preview=preview)


def test_digest_composer_respects_preferences() -> None:
    notifications = [_n("review", "New review comment"), _n("export", "Export finished")]
    prefs = {"review": _pref("review", email=False, preview=True)}
    result = compose_digest(notifications, prefs)  # review muted → only export
    assert result is not None
    subject, body = result
    assert "1 update" in subject
    assert "Export finished" in body
    assert "New review comment" not in body


def test_digest_privacy_titles_only_without_preview() -> None:
    notifications = [_n("review", "Comment on Chapter 2", body="the quoted thesis text")]
    result = compose_digest(notifications, {})  # no preview pref → titles only
    assert result is not None
    _, body = result
    assert "Comment on Chapter 2" in body
    assert "the quoted thesis text" not in body  # prose never leaks by default


def test_digest_none_when_everything_muted() -> None:
    notifications = [_n("review", "t")]
    prefs = {"review": _pref("review", email=False, preview=False)}
    assert compose_digest(notifications, prefs) is None


def test_sentry_off_by_default() -> None:
    from app.core.config import get_settings

    assert get_settings().SENTRY_DSN == ""


def test_digest_job_routed_to_maintenance_queue() -> None:
    from app.services.job_queue import _QUEUE_BY_KIND  # type: ignore[attr-defined]

    assert _QUEUE_BY_KIND.get("notification_digest") == "maintenance"
