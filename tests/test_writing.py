"""Private writing polish — LanguageTool (enterprise E7).

Advisory grammar/style suggestions; fully offline via httpx.MockTransport.
Fail-closed: no server / errors -> available=False with no matches. The check is
non-mutating and never touches verification state.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

import app.api.writing as wr
from app.models.project import Project
from app.writing.languagetool import check_text
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio

_LT_RESPONSE = {
    "matches": [
        {
            "message": "Possible spelling mistake found.",
            "shortMessage": "Spelling",
            "offset": 5,
            "length": 4,
            "replacements": [{"value": "text"}, {"value": "test"}],
            "rule": {"id": "MORFOLOGIK_RULE_EN_US", "issueType": "misspelling",
                     "category": {"id": "TYPOS", "name": "Possible Typo"}},
        }
    ]
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _settings(**over):
    base = {
        "LANGUAGETOOL_ENABLED": True,
        "LANGUAGETOOL_URL": "http://lt.local:8010",
        "LANGUAGETOOL_LANGUAGE": "en-US",
        "LANGUAGETOOL_API_KEY": "",
        "LANGUAGETOOL_USERNAME": "",
    }
    base.update(over)
    return type("S", (), base)()


# --- service -----------------------------------------------------------------


async def test_check_parses_matches(monkeypatch) -> None:
    monkeypatch.setattr("app.writing.languagetool.get_settings", lambda: _settings())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v2/check")
        return httpx.Response(200, json=_LT_RESPONSE)

    async with _client(handler) as client:
        result = await check_text(client, "Somе mistaken text", language="en-US")
    assert result["available"] is True
    m = result["matches"][0]
    assert m["category"] == "Possible Typo"
    assert m["replacements"] == ["text", "test"]
    assert m["rule_id"] == "MORFOLOGIK_RULE_EN_US"


async def test_no_url_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("app.writing.languagetool.get_settings", lambda: _settings(LANGUAGETOOL_URL=""))
    async with _client(lambda r: httpx.Response(200, json=_LT_RESPONSE)) as client:
        result = await check_text(client, "text")
    assert result["available"] is False
    assert result["matches"] == []


async def test_server_error_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr("app.writing.languagetool.get_settings", lambda: _settings())

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with _client(boom) as client:
        result = await check_text(client, "text")
    assert result["available"] is False and result["matches"] == []


async def test_long_text_is_truncated(monkeypatch) -> None:
    monkeypatch.setattr("app.writing.languagetool.get_settings", lambda: _settings())
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["len"] = len(request.content)
        return httpx.Response(200, json={"matches": []})

    async with _client(handler) as client:
        result = await check_text(client, "x " * 30_000)
    assert result["truncated"] is True


# --- API ---------------------------------------------------------------------


async def _project(db_session, user) -> Project:
    project = Project(user_id=user.id, title="W", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_status_endpoint(client: AsyncClient, user_a) -> None:
    resp = await client.get("/writing/status", cookies=auth_cookie(user_a))
    assert resp.status_code == 200
    # Disabled by default in tests.
    assert resp.json()["enabled"] is False


async def test_check_endpoint(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    project = await _project(db_session, user_a)
    monkeypatch.setattr(wr, "get_settings", lambda: _settings())
    monkeypatch.setattr("app.writing.languagetool.get_settings", lambda: _settings())
    monkeypatch.setattr(wr, "build_client", lambda transport=None: _client(
        lambda r: httpx.Response(200, json=_LT_RESPONSE)
    ))
    resp = await client.post(
        f"/projects/{project.id}/writing/check",
        json={"text": "Somе mistaken text"},
        cookies=auth_cookie(user_a),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["advisory"] is True
    assert body["matches"][0]["category"] == "Possible Typo"


async def test_check_disabled_503(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    project = await _project(db_session, user_a)
    monkeypatch.setattr(wr, "get_settings", lambda: _settings(LANGUAGETOOL_ENABLED=False))
    resp = await client.post(
        f"/projects/{project.id}/writing/check",
        json={"text": "text"},
        cookies=auth_cookie(user_a),
    )
    assert resp.status_code == 503


async def test_check_owner_guarded(client: AsyncClient, db_session, user_a, user_b, monkeypatch) -> None:
    project = await _project(db_session, user_a)
    monkeypatch.setattr(wr, "get_settings", lambda: _settings())
    resp = await client.post(
        f"/projects/{project.id}/writing/check",
        json={"text": "text"},
        cookies=auth_cookie(user_b),
    )
    assert resp.status_code == 404
