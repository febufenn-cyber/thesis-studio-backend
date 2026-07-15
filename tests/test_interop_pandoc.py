"""Pandoc universal interop (enterprise E6).

Real conversions run when the pandoc binary is present (skipped otherwise, so CI
without pandoc still passes); the disabled/format-error paths are deterministic.
The preview converter is non-mutating and the export path never fabricates.
"""

from __future__ import annotations

import base64

import pytest
from httpx import AsyncClient

import app.interop.pandoc as pd
from app.interop.pandoc import PandocError, PandocUnavailableError, convert, pandoc_available
from app.models.project import Project
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio

_HAS_PANDOC = pandoc_available()
_needs_pandoc = pytest.mark.skipif(not _HAS_PANDOC, reason="pandoc binary not installed")


# --- converter ---------------------------------------------------------------


@_needs_pandoc
async def test_convert_markdown_to_html() -> None:
    out = await convert("# Title\n\nHello **world**.", from_fmt="markdown", to_fmt="html")
    assert b"<strong>world</strong>" in out


@_needs_pandoc
async def test_convert_markdown_to_binary_odt() -> None:
    out = await convert("# Title", from_fmt="markdown", to_fmt="odt")
    assert out[:2] == b"PK"  # odt is a zip container


async def test_convert_rejects_unknown_format() -> None:
    with pytest.raises(PandocError):
        await convert("x", from_fmt="markdown", to_fmt="exe")
    with pytest.raises(PandocError):
        await convert("x", from_fmt="malware", to_fmt="html")


async def test_convert_disabled_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        pd, "get_settings", lambda: type("S", (), {"PANDOC_ENABLED": False, "PANDOC_BIN": "pandoc"})()
    )
    assert pandoc_available() is False
    with pytest.raises(PandocUnavailableError):
        await convert("x", from_fmt="markdown", to_fmt="html")


# --- API ---------------------------------------------------------------------


async def test_formats_endpoint(client: AsyncClient, user_a) -> None:
    resp = await client.get("/interop/formats", cookies=auth_cookie(user_a))
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is _HAS_PANDOC
    assert "markdown" in body["input_formats"]
    assert "docx" in body["output_formats"]


@_needs_pandoc
async def test_convert_preview_markdown_to_rst(client: AsyncClient, user_a) -> None:
    resp = await client.post(
        "/interop/convert/preview",
        json={"content": "# Heading\n\ntext", "from_fmt": "markdown", "to_fmt": "rst"},
        cookies=auth_cookie(user_a),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["encoding"] == "utf-8"
    assert "Heading" in body["content"]


@_needs_pandoc
async def test_convert_preview_binary_is_base64(client: AsyncClient, user_a) -> None:
    resp = await client.post(
        "/interop/convert/preview",
        json={"content": "# H", "from_fmt": "markdown", "to_fmt": "docx"},
        cookies=auth_cookie(user_a),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["encoding"] == "base64"
    assert base64.b64decode(body["content"])[:2] == b"PK"


async def test_convert_preview_requires_content(client: AsyncClient, user_a) -> None:
    if not _HAS_PANDOC:
        pytest.skip("pandoc not installed")
    resp = await client.post(
        "/interop/convert/preview",
        json={"from_fmt": "markdown", "to_fmt": "html"},
        cookies=auth_cookie(user_a),
    )
    assert resp.status_code == 400


@_needs_pandoc
async def test_export_pandoc_manuscript(client: AsyncClient, db_session, user_a) -> None:
    project = Project(
        user_id=user_a.id, title="Interop", meta={"title": "Interop Thesis"}, front_matter=[],
        chapters=[{"number": 1, "title": "Intro", "blocks": [
            {"type": "paragraph", "runs": [{"text": "Hello world."}]}
        ]}],
        works_cited=[],
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    resp = await client.post(
        f"/projects/{project.id}/export/pandoc", json={"to": "rst"}, cookies=auth_cookie(user_a)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "rst"
    assert "Hello world." in body["content"]


async def test_export_pandoc_disabled_503(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.interop_pandoc.pandoc_available", lambda: False
    )
    project = Project(
        user_id=user_a.id, title="Interop", meta={"title": "T"}, front_matter=[],
        chapters=[], works_cited=[],
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    resp = await client.post(
        f"/projects/{project.id}/export/pandoc", json={"to": "odt"}, cookies=auth_cookie(user_a)
    )
    assert resp.status_code == 503
