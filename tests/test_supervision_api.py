"""Committee + block-comment + diff API (docs/LLD.md 3.6)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.collaboration.committee import committee_permissions, CommitteeRole, SupervisionPermission
from app.models.project import Project
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


def test_permission_table_is_deny_by_default() -> None:
    assert SupervisionPermission.APPROVE_ACADEMIC in committee_permissions(CommitteeRole.ADVISOR)
    assert SupervisionPermission.APPROVE_ACADEMIC not in committee_permissions(CommitteeRole.COMMITTEE_MEMBER)
    assert committee_permissions("not_a_role") == frozenset()


async def _project(db_session, user, block_id: str | None = None) -> Project:
    blocks = []
    if block_id:
        blocks = [{"id": block_id, "type": "paragraph", "runs": [{"text": "Anchor me"}]}]
    project = Project(
        user_id=user.id, title="Sup", meta={}, front_matter=[],
        chapters=[{"number": 1, "title": "C", "blocks": blocks}], works_cited=[],
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_owner_assigns_committee_and_member_can_comment(
    client: AsyncClient, db_session, user_a, user_b
) -> None:
    block_id = str(uuid4())
    project = await _project(db_session, user_a, block_id)

    assign = await client.post(
        f"/projects/{project.id}/committee",
        json={"user_id": str(user_b.id), "committee_role": "advisor"},
        cookies=auth_cookie(user_a),
    )
    assert assign.status_code == 201

    # Advisor (user_b) can now comment.
    comment = await client.post(
        f"/projects/{project.id}/block-comments",
        json={"canonical_block_id": block_id, "body": "Please expand this."},
        cookies=auth_cookie(user_b),
    )
    assert comment.status_code == 201
    assert comment.json()["committee_role"] == "advisor"
    assert comment.json()["anchor_state"] == "current"


async def test_non_member_cannot_comment(client: AsyncClient, db_session, user_a, user_b) -> None:
    block_id = str(uuid4())
    project = await _project(db_session, user_a, block_id)
    response = await client.post(
        f"/projects/{project.id}/block-comments",
        json={"canonical_block_id": block_id, "body": "hi"},
        cookies=auth_cookie(user_b),
    )
    assert response.status_code == 404


async def test_comment_on_unknown_block_is_400(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a, str(uuid4()))
    response = await client.post(
        f"/projects/{project.id}/block-comments",
        json={"canonical_block_id": str(uuid4()), "body": "hi"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 400


async def test_comment_survives_rerender_but_flags_edit(
    client: AsyncClient, db_session, user_a
) -> None:
    block_id = str(uuid4())
    project = await _project(db_session, user_a, block_id)
    await client.post(
        f"/projects/{project.id}/block-comments",
        json={"canonical_block_id": block_id, "body": "note"},
        cookies=auth_cookie(user_a),
    )
    # Edit the block's text (same id) -> anchor should become block_changed.
    project.chapters = [{"number": 1, "title": "C", "blocks": [
        {"id": block_id, "type": "paragraph", "runs": [{"text": "Anchor me — now edited"}]}
    ]}]
    await db_session.commit()

    listing = await client.get(
        f"/projects/{project.id}/block-comments", cookies=auth_cookie(user_a)
    )
    assert listing.status_code == 200
    assert listing.json()["comments"][0]["anchor_state"] == "block_changed"


async def test_diff_endpoint(client: AsyncClient, db_session, user_a) -> None:
    a = str(uuid4())
    project = await _project(db_session, user_a, a)
    base_doc = {
        "meta": {}, "front_matter": [],
        "chapters": [{"number": 1, "title": "C", "blocks": [
            {"id": a, "type": "paragraph", "runs": [{"text": "Original claim"}]}
        ]}],
        "works_cited": [],
    }
    response = await client.post(
        f"/projects/{project.id}/diff",
        json={"base_document": base_doc},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    # Current block text ("Anchor me") differs in meaning from base.
    assert response.json()["summary"].get("meaning_changed") == 1
