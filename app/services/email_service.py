"""Email service — sends transactional emails via the Resend HTTP API.

In development with no RESEND_API_KEY set, emails are logged instead of sent.
This makes local dev frictionless without disabling the magic-link flow.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings


log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


async def send_magic_link_email(to_email: str, link_url: str) -> None:
    """Send the sign-in email containing the one-time magic link.

    In development (no RESEND_API_KEY), logs the link to stdout instead.
    The student can click the link from terminal output.
    """
    settings = get_settings()

    subject = "Sign in to Robofox Thesis Studio"
    html_body = _magic_link_html(link_url)
    text_body = _magic_link_text(link_url)

    if not settings.RESEND_API_KEY:
        log.warning(
            "RESEND_API_KEY not set — magic link for %s NOT sent. Link: %s",
            to_email, link_url,
        )
        return

    payload = {
        "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>",
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(RESEND_API_URL, json=payload, headers=headers)
        if response.status_code >= 400:
            log.error(
                "Resend API error: status=%d body=%s",
                response.status_code, response.text[:500],
            )
            response.raise_for_status()


def _magic_link_html(url: str) -> str:
    return f"""\
<!doctype html>
<html>
<body style="font-family: system-ui, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px;">
  <h2 style="color: #1a1a1a;">Sign in to Robofox Thesis Studio</h2>
  <p>Click the button below to sign in. The link expires in 15 minutes and can only be used once.</p>
  <p style="margin: 32px 0;">
    <a href="{url}" style="display: inline-block; background: #1a1a1a; color: #fff;
       padding: 12px 24px; text-decoration: none; border-radius: 6px;">
      Sign in
    </a>
  </p>
  <p style="color: #666; font-size: 14px;">
    Or copy this link into your browser:<br>
    <a href="{url}" style="color: #666; word-break: break-all;">{url}</a>
  </p>
  <p style="color: #999; font-size: 12px; margin-top: 32px;">
    If you didn't request this, you can ignore this email.
  </p>
</body>
</html>"""


def _magic_link_text(url: str) -> str:
    return f"""\
Sign in to Robofox Thesis Studio

Click this link to sign in. It expires in 15 minutes and can only be used once.

{url}

If you didn't request this, you can ignore this email.
"""


async def send_otp_email(to_email: str, code: str) -> None:
    """Send the 6-digit sign-in code. Logs instead when RESEND_API_KEY is unset."""
    settings = get_settings()

    if not settings.RESEND_API_KEY:
        log.warning(
            "RESEND_API_KEY not set — OTP for %s NOT sent. Code: %s", to_email, code
        )
        return

    payload = {
        "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>",
        "to": [to_email],
        "subject": f"{code} is your Robofox Thesis Studio sign-in code",
        "html": (
            '<div style="font-family: system-ui, sans-serif; max-width: 560px;'
            ' margin: 0 auto; padding: 32px;">'
            "<h2>Your sign-in code</h2>"
            f'<p style="font-size: 32px; letter-spacing: 8px; font-weight: 700;">{code}</p>'
            "<p>This code expires in 10 minutes. If you didn't request it, ignore this email.</p>"
            "</div>"
        ),
        "text": (
            f"Your Robofox Thesis Studio sign-in code is: {code}\n\n"
            "It expires in 10 minutes. If you didn't request it, ignore this email."
        ),
    }
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(RESEND_API_URL, json=payload, headers=headers)
        if response.status_code >= 400:
            log.error(
                "Resend API error (otp): status=%d body=%s",
                response.status_code, response.text[:500],
            )
            response.raise_for_status()
