"""CSL bibliography rendering (enterprise E5).

citeproc renders registry sources in any CSL style. The bundled 'harvard1' style
renders fully offline; other styles fetch from the CSL repository (mocked here).
A formatter, never a fact source: only registry fields appear, unparseable styles
fail closed, and [VERIFY] placeholders never reach the bibliography.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

from app.models.project import Project
from app.models.source import Source
from app.references.csl_render import CSLRenderError, render_bibliography
from app.references.csl_styles import friendly_style_id, resolve_style_xml
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio

_ITEM = {
    "id": "vaswani2017",
    "type": "article-journal",
    "title": "Attention Is All You Need",
    "author": [{"family": "Vaswani", "given": "Ashish"}],
    "container-title": "NeurIPS",
    "issued": {"date-parts": [[2017]]},
    "volume": "30",
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- pure renderer -----------------------------------------------------------


async def test_render_with_bundled_style() -> None:
    xml = await resolve_style_xml(None, "harvard1", enabled=False)
    assert xml is not None
    entries = render_bibliography([_ITEM], xml)
    assert len(entries) == 1
    assert "Vaswani" in entries[0]
    assert "2017" in entries[0]
    assert "Attention Is All You Need" in entries[0]


async def test_render_text_output() -> None:
    xml = await resolve_style_xml(None, "harvard1", enabled=False)
    entries = render_bibliography([_ITEM], xml, output="text")
    assert "<i>" not in entries[0]  # plain text carries no HTML tags


async def test_render_empty_items() -> None:
    xml = await resolve_style_xml(None, "harvard1", enabled=False)
    assert render_bibliography([], xml) == []


async def test_unparseable_style_fails_closed() -> None:
    with pytest.raises(CSLRenderError):
        render_bibliography([_ITEM], "<not-a-csl-style>oops")


# --- style resolution --------------------------------------------------------


async def test_bundled_resolves_offline() -> None:
    assert await resolve_style_xml(None, "harvard1", enabled=False) is not None


async def test_unknown_style_disabled_returns_none() -> None:
    # Enabled but no client -> cannot fetch -> None (fail-closed).
    assert await resolve_style_xml(None, "apa", enabled=True) is None


async def test_alias_maps_to_repo_id() -> None:
    assert friendly_style_id("mla") == "modern-language-association"
    assert friendly_style_id("APA") == "apa"


async def test_fetch_from_repository() -> None:
    harvard = await resolve_style_xml(None, "harvard1", enabled=False)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, text=harvard)

    # A style id not seen before must be requested from the repo.
    async with _client(handler) as client:
        xml = await resolve_style_xml(client, "ieee", enabled=True)
    assert xml is not None
    assert captured["url"].endswith("/ieee.csl")


async def test_fetch_path_traversal_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not be called
        raise AssertionError("network should not be reached for a malicious id")

    async with _client(handler) as client:
        assert await resolve_style_xml(client, "../../etc/passwd", enabled=True) is None


async def test_fetch_404_fails_closed() -> None:
    async with _client(lambda r: httpx.Response(404, text="Not Found")) as client:
        assert await resolve_style_xml(client, "no-such-style-xyz", enabled=True) is None


# --- API ---------------------------------------------------------------------


async def _project_with_source(db_session, user, *, title: str):
    project = Project(user_id=user.id, title="Bib", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.flush()
    source = Source(
        project_id=project.id, user_id=user.id, kind="journal",
        fields={"author": "Vaswani, Ashish", "title": title, "year": "2017", "container": "NeurIPS"},
        parse_status="imported",
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_render_endpoint_bundled_style(client: AsyncClient, db_session, user_a) -> None:
    project = await _project_with_source(db_session, user_a, title="Attention Is All You Need")
    resp = await client.post(
        f"/projects/{project.id}/bibliography/render",
        json={"style": "harvard1"},
        cookies=auth_cookie(user_a),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert "Vaswani" in body["entries"][0]
    assert "Attention Is All You Need" in body["entries"][0]


async def test_render_endpoint_unresolvable_style_422(client: AsyncClient, db_session, user_a) -> None:
    # CSL_ENABLED is false in tests, so a non-bundled style cannot be fetched.
    project = await _project_with_source(db_session, user_a, title="X")
    resp = await client.post(
        f"/projects/{project.id}/bibliography/render",
        json={"style": "apa"},
        cookies=auth_cookie(user_a),
    )
    assert resp.status_code == 422


async def test_render_endpoint_owner_guarded(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = await _project_with_source(db_session, user_a, title="X")
    resp = await client.post(
        f"/projects/{project.id}/bibliography/render",
        json={"style": "harvard1"},
        cookies=auth_cookie(user_b),
    )
    assert resp.status_code == 404


async def test_styles_listing(client: AsyncClient, user_a) -> None:
    resp = await client.get("/bibliography/styles", cookies=auth_cookie(user_a))
    assert resp.status_code == 200
    body = resp.json()
    assert body["bundled"] == "harvard1"
    assert "apa" in body["aliases"] and "mla" in body["aliases"]
