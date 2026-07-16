"""Daily notification email digests.

Closes the delivery gap: notifications existed only in-app. Once a day the
maintenance loop composes one email per user summarising unread notifications
from the last day — honoring NotificationPreference rows exactly:

* a user is emailed only if at least one preference has ``email_enabled``;
* a notification KIND is included only when its preference (if any) has
  ``email_enabled`` (kinds without a stored preference inherit the default
  ``email_enabled=True``);
* bodies are included only for kinds whose preference sets
  ``content_preview`` — otherwise titles only (privacy default: notification
  content never leaks thesis prose, and the digest keeps that promise).

Config-gated: without RESEND_API_KEY the composer still works (tested) but
sending is skipped with a log line, never an error.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.tenancy import Notification, NotificationPreference
from app.models.user import User

logger = logging.getLogger(__name__)

DIGEST_WINDOW_HOURS = 24
DIGEST_MAX_ITEMS = 20


def compose_digest(
    notifications: list[Notification],
    prefs_by_kind: dict[str, NotificationPreference],
) -> tuple[str, str] | None:
    """(subject, body) for one user's digest, or None if nothing to send."""
    included: list[Notification] = []
    for n in notifications:
        pref = prefs_by_kind.get(n.kind)
        if pref is not None and not pref.email_enabled:
            continue
        included.append(n)
    if not included:
        return None

    lines: list[str] = []
    for n in included[:DIGEST_MAX_ITEMS]:
        pref = prefs_by_kind.get(n.kind)
        show_body = bool(pref and pref.content_preview)
        lines.append(f"• {n.title}")
        if show_body and n.body:
            lines.append(f"  {n.body[:280]}")
    if len(included) > DIGEST_MAX_ITEMS:
        lines.append(f"…and {len(included) - DIGEST_MAX_ITEMS} more in the app.")

    count = len(included)
    subject = f"Acadensia digest — {count} update{'s' if count != 1 else ''} on your manuscripts"
    body = (
        "Here's what happened in the last day:\n\n"
        + "\n".join(lines)
        + "\n\nOpen Acadensia to act on any of these. "
        "You can tune or disable this digest in Settings → notifications."
    )
    return subject, body


async def send_daily_digests(db: AsyncSession) -> int:
    """Compose and send digests for every eligible user. Returns emails sent."""
    settings = get_settings()
    since = datetime.now(timezone.utc) - timedelta(hours=DIGEST_WINDOW_HOURS)

    rows = (
        (
            await db.execute(
                select(Notification)
                .where(Notification.created_at >= since, Notification.read_at.is_(None))
                .order_by(Notification.user_id, Notification.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    by_user: dict = {}
    for n in rows:
        by_user.setdefault(n.user_id, []).append(n)

    prefs = (
        (await db.execute(select(NotificationPreference))).scalars().all()
    )
    prefs_by_user: dict = {}
    for p in prefs:
        prefs_by_user.setdefault(p.user_id, {})[p.kind] = p

    sent = 0
    for user_id, items in by_user.items():
        user_prefs = prefs_by_user.get(user_id, {})
        # An account that switched every stored preference off is never mailed.
        if user_prefs and not any(p.email_enabled for p in user_prefs.values()):
            continue
        digest = compose_digest(items, user_prefs)
        if digest is None:
            continue
        subject, body = digest
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            continue
        if not settings.RESEND_API_KEY:
            logger.info("digest composed for %s but RESEND_API_KEY unset; skipping send", user.email)
            continue
        try:
            from app.services.email_service import send_digest_email

            await send_digest_email(user.email, subject, body)
            sent += 1
        except Exception as exc:  # a mail failure must never break the sweep
            logger.warning("digest send failed for %s: %s", user.email, exc)
    return sent
