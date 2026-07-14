"""Interchange export/import API (docs/LLD.md 3.5)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from httpx import AsyncClient

from app.models.project import Project
from app.models.source import Source
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


async def _project(db_session, user) -> Project:
    project = Project(
        user_id=user.id, title="Interchange", meta={"title": "Interchange Thesis"},
        front_matter=[],
        chapters=[{"number": 1, "title": "Intro", "blocks": [
            {"type": "paragraph", "runs": [{"text": "Hello world."}]}
        ]}],
        works_cited=[],
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_export_jats_returns_well_formed_xml(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    response = await client.get(f"/projects/{project.id}/export/jats", cookies=auth_cookie(user_a))
    assert response.status_code == 200
    xml = response.json()["content"]
    ET.fromstring(xml)
    assert "Interchange Thesis" in xml


async def test_export_latex_and_csl(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    source = Source(project_id=project.id, user_id=user_a.id, kind="book",
                    fields={"author": "Austen, Jane", "title": "Emma", "publisher": "J. Murray", "year": "1815"},
                    parse_status="imported")
    db_session.add(source)
    await db_session.commit()

    latex = await client.get(f"/projects/{project.id}/export/latex", cookies=auth_cookie(user_a))
    assert latex.status_code == 200
    assert "\\documentclass" in latex.json()["content"]

    csl = await client.get(f"/projects/{project.id}/export/csl", cookies=auth_cookie(user_a))
    assert csl.status_code == 200
    assert csl.json()["items"][0]["title"] == "Emma"


async def test_latex_import_preview(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    latex = r"\begin{document}\section{Intro}A paragraph. \cite{k1}\end{document}"
    response = await client.post(
        f"/projects/{project.id}/import/latex/preview",
        json={"content": latex},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["chapters"] == 1
    assert body["unresolved_citations"] == 1


async def test_latex_import_unsupported_is_422(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    response = await client.post(
        f"/projects/{project.id}/import/latex/preview",
        json={"content": r"\begin{document}\includegraphics{x}\end{document}"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 422


async def test_export_is_owner_guarded(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = await _project(db_session, user_a)
    response = await client.get(f"/projects/{project.id}/export/jats", cookies=auth_cookie(user_b))
    assert response.status_code == 404


async def test_csl_import_via_references_endpoint(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    csl = '[{"type":"book","title":"Emma","author":[{"family":"Austen","given":"Jane"}],"issued":{"date-parts":[[1815]]},"publisher":"J. Murray"}]'
    response = await client.post(
        f"/projects/{project.id}/references/import",
        json={"format": "csl", "content": csl},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    assert response.json()["imported"] == 1
