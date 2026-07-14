"""API surface for citation styles and BibTeX export."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.project import Project
from app.models.source import Source
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


def _project(user_id) -> Project:
    return Project(
        user_id=user_id,
        title="Bib Project",
        meta={},
        front_matter=[],
        chapters=[],
        works_cited=[],
    )


async def test_citation_styles_endpoint(client: AsyncClient, user_a) -> None:
    response = await client.get("/citation-styles", cookies=auth_cookie(user_a))
    assert response.status_code == 200
    data = response.json()
    keys = {s["key"] for s in data["styles"]}
    assert {"mla-9", "ieee-2021", "apa-7"} <= keys
    assert data["default"] == "mla-9"


async def test_references_bibtex_export(client: AsyncClient, db_session, user_a) -> None:
    project = _project(user_a.id)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    db_session.add(
        Source(
            project_id=project.id,
            user_id=user_a.id,
            kind="book",
            fields={
                "author": "Achebe, Chinua",
                "title": "Things Fall Apart",
                "publisher": "Heinemann",
                "year": "1958",
            },
            verified=True,
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/projects/{project.id}/references.bib", cookies=auth_cookie(user_a)
    )
    assert response.status_code == 200
    assert "application/x-bibtex" in response.headers["content-type"]
    assert "@book{Achebe1958," in response.text


async def test_references_bibtex_is_isolated(
    client: AsyncClient, db_session, user_a, user_b
) -> None:
    project = _project(user_a.id)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    # Another user cannot read the registry (404, never 403).
    response = await client.get(
        f"/projects/{project.id}/references.bib", cookies=auth_cookie(user_b)
    )
    assert response.status_code == 404
