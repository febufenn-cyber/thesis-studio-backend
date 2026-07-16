"""Robofox guide — playbooks and start-from-zero scaffolding."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.guide.playbooks import list_playbooks
from app.models.project import Project
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


def test_playbooks_are_complete() -> None:
    books = list_playbooks()
    keys = {p["key"] for p in books}
    assert {"ma_dissertation", "engineering_project_report",
            "imrad_journal_article", "neurips_paper", "generic"} <= keys
    for p in books:
        assert p["topic_worksheet"] and p["methodology"] and p["skeleton"], p["key"]
        # Skeleton prompts must be questions/instructions, never finished prose:
        # every block the scaffold creates is [TO WRITE]-prefixed downstream.
        for _n, title, prompts in p["skeleton"]:
            assert title and prompts


async def test_scaffold_creates_prompt_skeleton(client: AsyncClient, db_session, user_a) -> None:
    project = Project(user_id=user_a.id, title="From Zero", meta={}, front_matter=[],
                      chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    resp = await client.post(
        f"/projects/{project.id}/guide/scaffold",
        json={"playbook": "engineering_project_report"},
        cookies=auth_cookie(user_a),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["chapters_created"] == 6

    await db_session.refresh(project)
    assert len(project.chapters) == 6
    first_text = project.chapters[0]["blocks"][0]["runs"][0]["text"]
    assert first_text.startswith("[TO WRITE]")  # prompts, never prose
    assert (project.meta or {}).get("guide_playbook") == "engineering_project_report"

    # Regression: ids must be minted once and PERSISTED. Id-less chapter dicts
    # get fresh UUIDs on every model validation, so the id the structure tree
    # returns never matches the next request — opening any scaffolded chapter
    # 404s. The stored payload must therefore carry stable ids.
    for chapter in project.chapters:
        assert chapter.get("id"), "scaffolded chapter must persist its id"
        for block in chapter["blocks"]:
            assert block.get("id"), "scaffolded block must persist its id"

    # And the editor can actually open a scaffolded chapter by the id the
    # structure endpoint hands out (the exact end-to-end failure mode).
    structure = await client.get(
        f"/projects/{project.id}/editor/structure", cookies=auth_cookie(user_a)
    )
    assert structure.status_code == 200
    first_id = structure.json()["chapters"][0]["id"]
    opened = await client.get(
        f"/projects/{project.id}/editor/chapters/{first_id}", cookies=auth_cookie(user_a)
    )
    assert opened.status_code == 200
    assert opened.json()["chapter"]["id"] == first_id


async def test_scaffold_never_overwrites(client: AsyncClient, db_session, user_a) -> None:
    project = Project(user_id=user_a.id, title="Has Work", meta={}, front_matter=[],
                      chapters=[{"number": 1, "title": "Mine", "blocks": []}], works_cited=[])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    resp = await client.post(
        f"/projects/{project.id}/guide/scaffold",
        json={"playbook": "generic"}, cookies=auth_cookie(user_a),
    )
    assert resp.status_code == 409  # the guide never clobbers student work


async def test_scaffold_owner_guarded_and_unknown_playbook(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = Project(user_id=user_a.id, title="P", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    assert (await client.post(f"/projects/{project.id}/guide/scaffold",
                              json={"playbook": "generic"}, cookies=auth_cookie(user_b))).status_code == 404
    assert (await client.post(f"/projects/{project.id}/guide/scaffold",
                              json={"playbook": "astrology"}, cookies=auth_cookie(user_a))).status_code == 422
