"""API surface for reference import (BibTeX/RIS -> unverified registry sources)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.project import Project
from app.models.source import Source
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


def _project(user_id) -> Project:
    return Project(
        user_id=user_id,
        title="Import Project",
        meta={},
        front_matter=[],
        chapters=[],
        works_cited=[],
    )


_BIBTEX = """
@book{Achebe1958,
  author = {Achebe, Chinua},
  title = {Things Fall Apart},
  publisher = {Heinemann},
  year = {1958}
}
"""


async def test_import_bibtex_creates_unverified_sources(
    client: AsyncClient, db_session, user_a
) -> None:
    project = _project(user_a.id)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    response = await client.post(
        f"/projects/{project.id}/references/import",
        json={"format": "bibtex", "content": _BIBTEX},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["imported"] >= 1
    assert sum(data["kinds"].values()) == data["imported"]

    sources = list(
        (
            await db_session.execute(select(Source).where(Source.project_id == project.id))
        ).scalars()
    )
    assert len(sources) == data["imported"]
    assert all(s.verified is False for s in sources)
    assert all(s.parse_status == "imported" for s in sources)


async def test_import_is_isolated(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = _project(user_a.id)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    response = await client.post(
        f"/projects/{project.id}/references/import",
        json={"format": "bibtex", "content": _BIBTEX},
        cookies=auth_cookie(user_b),
    )
    assert response.status_code == 404
