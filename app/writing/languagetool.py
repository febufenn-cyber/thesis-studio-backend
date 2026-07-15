"""LanguageTool grammar/style checking (enterprise E7).

Advisory writing feedback — grammar, spelling, punctuation and style — from a
LanguageTool server. Point ``LANGUAGETOOL_URL`` at a self-hosted instance so the
manuscript text never leaves the deployment ("private polish"); the public
endpoint also works for light use.

This is purely advisory: it returns *suggested* edits with positions, never
rewrites the manuscript and never touches any verified/citation state. Fail
closed: if the server is unreachable the result is an empty, explicitly
``unavailable`` set — never invented corrections.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings

__all__ = ["check_text"]

_MAX_CHARS = 40_000


def _endpoint() -> str:
    base = (getattr(get_settings(), "LANGUAGETOOL_URL", "") or "").rstrip("/")
    return f"{base}/v2/check" if base else ""


def _parse_matches(payload: dict) -> list[dict]:
    matches: list[dict] = []
    for m in payload.get("matches") or []:
        rule = m.get("rule") or {}
        category = rule.get("category") or {}
        matches.append(
            {
                "message": m.get("message", ""),
                "short_message": m.get("shortMessage", ""),
                "offset": int(m.get("offset", 0)),
                "length": int(m.get("length", 0)),
                "replacements": [
                    r.get("value", "") for r in (m.get("replacements") or []) if r.get("value")
                ][:5],
                "rule_id": rule.get("id", ""),
                "category": category.get("name", "") or category.get("id", ""),
                "issue_type": rule.get("issueType", ""),
            }
        )
    return matches


async def check_text(
    client: httpx.AsyncClient, text: str, *, language: str | None = None
) -> dict:
    """Return advisory writing suggestions for ``text``.

    ``{"available": bool, "language": str, "matches": [...], "truncated": bool}``.
    A server error yields ``available=False`` with no matches (fail-closed).
    """
    settings = get_settings()
    lang = language or getattr(settings, "LANGUAGETOOL_LANGUAGE", "en-US") or "en-US"
    endpoint = _endpoint()
    body = (text or "").strip()
    if not endpoint or not body:
        return {"available": bool(endpoint), "language": lang, "matches": [], "truncated": False}

    truncated = len(body) > _MAX_CHARS
    if truncated:
        body = body[:_MAX_CHARS]

    data = {"text": body, "language": lang}
    api_key = getattr(settings, "LANGUAGETOOL_API_KEY", "")
    username = getattr(settings, "LANGUAGETOOL_USERNAME", "")
    if api_key and username:
        data["apiKey"] = api_key
        data["username"] = username

    try:
        resp = await client.post(
            endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except httpx.HTTPError:
        return {"available": False, "language": lang, "matches": [], "truncated": truncated}
    if resp.status_code != 200:
        return {"available": False, "language": lang, "matches": [], "truncated": truncated}
    try:
        payload = resp.json() or {}
    except ValueError:
        return {"available": False, "language": lang, "matches": [], "truncated": truncated}

    return {
        "available": True,
        "language": lang,
        "matches": _parse_matches(payload),
        "truncated": truncated,
    }
