"""Database-backed Phase 2 API and persistence tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_command import DocumentCommand
from app.models.document_preview import DocumentPreview
from app.models.document_snapshot import DocumentSnapshot
from app.models.review_item import ReviewItem
from app.models.user import User
from tests.conftest import auth_cookie


pytestmark = pytest.mark.asyncio


async def _project(client: AsyncClient, user: User) -> dict:
    response = await client.post(
        "/projects",
        json={"title": "Phase 2 Thesis", "format_profile": "mla_strict"},
        cookies=auth_cookie(user),
    )
    assert response.status_code == 201
    project = response.json()
    seeded = await client.patch(
        f"/projects/{project['id']}/chapters",
        json={
            "expected_version": project["document_version"],
            "chapters": [
                {
                    "number": 1,
                    "title": "Introduction",
                    "status": "in_progress",
                    "blocks": [
                        {
                            "type": "paragraph",
                            "runs": [{"text": "Original paragraph."}],
                        },
                        {
                            "type": "heading",
                            "level": 2,
                            "text": "Research background",
                        },
                    ],
                },
                {
                    "number": 2,
                    "title": "Analysis",
                    "status": "imported",
                    "blocks": [
                        {
                            "type": "paragraph",
                            "runs": [{"text": "Analysis begins here."}],
                        }
                    ],
                },
            ],
        },
        cookies=auth_cookie(user),
    )
    assert seeded.status_code == 200
    return seeded.json()


async def test_command_is_versioned_idempotent_and_undoable(
    client: AsyncClient,
    user_a: User,
    db_session: AsyncSession,
) -> None:
    project = await _project(client, user_a)
    chapter = project["chapters"][0]
    block = chapter["blocks"][0]
    request_id = f"save-{uuid4()}"
    payload = {
        "command_type": "update_block_text",
        "payload": {
            "block_id": block["id"],
            "runs": [{"text": "Safely revised paragraph.", "italic": False}],
        },
        "expected_document_version": project["document_version"],
        "client_request_id": request_id,
    }
    response = await client.post(
        f"/projects/{project['id']}/editor/commands",
        json=payload,
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    applied = response.json()
    assert applied["document_version"] == project["document_version"] + 1
    assert applied["command"]["target_id"] == block["id"]

    # Browser retry with the same request ID returns the same durable command
    # instead of applying the edit a second time.
    retry = await client.post(
        f"/projects/{project['id']}/editor/commands",
        json={**payload, "expected_document_version": applied["document_version"]},
        cookies=auth_cookie(user_a),
    )
    assert retry.status_code == 200
    assert retry.json()["command"]["id"] == applied["command"]["id"]
    count = (
        await db_session.execute(
            select(DocumentCommand).where(DocumentCommand.project_id == project["id"])
        )
    ).scalars().all()
    assert len(count) == 1

    stale = await client.post(
        f"/projects/{project['id']}/editor/commands",
        json={
            "command_type": "update_metadata",
            "payload": {"path": "guide.name", "value": "Dr. Devi"},
            "expected_document_version": project["document_version"],
        },
        cookies=auth_cookie(user_a),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_version"] == applied["document_version"]

    undo = await client.post(
        f"/projects/{project['id']}/editor/commands/{applied['command']['id']}/undo",
        json={"expected_document_version": applied["document_version"]},
        cookies=auth_cookie(user_a),
    )
    assert undo.status_code == 200
    restored = await client.get(
        f"/projects/{project['id']}/editor/chapters/{chapter['id']}",
        cookies=auth_cookie(user_a),
    )
    assert restored.json()["chapter"]["blocks"][0]["runs"][0]["text"] == "Original paragraph."


async def test_cross_chapter_move_undo_restores_both_containers(
    client: AsyncClient,
    user_a: User,
) -> None:
    project = await _project(client, user_a)
    first, second = project["chapters"]
    moving_id = first["blocks"][0]["id"]
    moved = await client.post(
        f"/projects/{project['id']}/editor/commands",
        json={
            "command_type": "move_block",
            "payload": {
                "block_id": moving_id,
                "to_chapter_id": second["id"],
                "to_index": 1,
            },
            "expected_document_version": project["document_version"],
        },
        cookies=auth_cookie(user_a),
    )
    assert moved.status_code == 200
    moved_data = moved.json()
    second_after = await client.get(
        f"/projects/{project['id']}/editor/chapters/{second['id']}",
        cookies=auth_cookie(user_a),
    )
    assert moving_id in [block["id"] for block in second_after.json()["chapter"]["blocks"]]

    undone = await client.post(
        f"/projects/{project['id']}/editor/commands/{moved_data['command']['id']}/undo",
        json={"expected_document_version": moved_data["document_version"]},
        cookies=auth_cookie(user_a),
    )
    assert undone.status_code == 200
    first_after = await client.get(
        f"/projects/{project['id']}/editor/chapters/{first['id']}",
        cookies=auth_cookie(user_a),
    )
    second_restored = await client.get(
        f"/projects/{project['id']}/editor/chapters/{second['id']}",
        cookies=auth_cookie(user_a),
    )
    assert moving_id in [block["id"] for block in first_after.json()["chapter"]["blocks"]]
    assert moving_id not in [block["id"] for block in second_restored.json()["chapter"]["blocks"]]


async def test_snapshots_compare_restore_and_cross_user_isolation(
    client: AsyncClient,
    user_a: User,
    user_b: User,
    db_session: AsyncSession,
) -> None:
    project = await _project(client, user_a)
    snapshot = await client.post(
        f"/projects/{project['id']}/editor/snapshots",
        json={
            "name": "Before supervisor corrections",
            "expected_document_version": project["document_version"],
        },
        cookies=auth_cookie(user_a),
    )
    assert snapshot.status_code == 200
    snapshot_data = snapshot.json()

    changed = await client.post(
        f"/projects/{project['id']}/editor/commands",
        json={
            "command_type": "update_metadata",
            "payload": {"path": "guide.name", "value": "Dr. R. Devi"},
            "expected_document_version": project["document_version"],
        },
        cookies=auth_cookie(user_a),
    )
    assert changed.status_code == 200
    comparison = await client.get(
        f"/projects/{project['id']}/editor/snapshots/{snapshot_data['id']}/compare",
        cookies=auth_cookie(user_a),
    )
    assert comparison.status_code == 200
    assert comparison.json()["comparison"]["metadata_changed"] is True

    forbidden = await client.get(
        f"/projects/{project['id']}/editor/snapshots",
        cookies=auth_cookie(user_b),
    )
    assert forbidden.status_code == 404

    restored = await client.post(
        f"/projects/{project['id']}/editor/snapshots/{snapshot_data['id']}/restore",
        json={"expected_document_version": changed.json()["document_version"]},
        cookies=auth_cookie(user_a),
    )
    assert restored.status_code == 200
    row_count = (
        await db_session.execute(
            select(DocumentSnapshot).where(DocumentSnapshot.project_id == project["id"])
        )
    ).scalars().all()
    # Manual checkpoint plus automatic pre-restore checkpoint. The command service
    # may also create its first editor snapshot, which is deliberately retained.
    assert len(row_count) >= 2


async def test_review_items_persist_and_reappear_until_underlying_issue_is_fixed(
    client: AsyncClient,
    user_a: User,
    db_session: AsyncSession,
) -> None:
    project = await _project(client, user_a)
    first = await client.get(
        f"/projects/{project['id']}/review-items",
        cookies=auth_cookie(user_a),
    )
    assert first.status_code == 200
    rows = first.json()
    metadata = next(item for item in rows if item["rule"] == "required_metadata_missing")
    assert metadata["status"] == "open"

    # Blocking deterministic findings cannot be dismissed manually.
    blocked = await client.patch(
        f"/projects/{project['id']}/review-items/{metadata['id']}",
        json={
            "action": "resolve",
            "note": "Ignore this",
            "expected_document_version": project["document_version"],
        },
        cookies=auth_cookie(user_a),
    )
    assert blocked.status_code == 409

    second = await client.get(
        f"/projects/{project['id']}/review-items",
        cookies=auth_cookie(user_a),
    )
    same = next(item for item in second.json() if item["rule"] == metadata["rule"] and item["location"] == metadata["location"])
    assert same["id"] == metadata["id"]
    stored = (
        await db_session.execute(
            select(ReviewItem).where(ReviewItem.id == metadata["id"])
        )
    ).scalar_one()
    assert stored.last_seen_version == project["document_version"]


async def test_structured_search_and_preview_cache(
    client: AsyncClient,
    user_a: User,
    db_session: AsyncSession,
) -> None:
    project = await _project(client, user_a)
    search = await client.get(
        f"/projects/{project['id']}/editor/search?q=type:heading background",
        cookies=auth_cookie(user_a),
    )
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["results"][0]["block_type"] == "heading"

    preview = await client.post(
        f"/projects/{project['id']}/previews",
        json={"expected_document_version": project["document_version"]},
        cookies=auth_cookie(user_a),
    )
    assert preview.status_code == 202
    first = preview.json()
    repeated = await client.post(
        f"/projects/{project['id']}/previews",
        json={"expected_document_version": project["document_version"]},
        cookies=auth_cookie(user_a),
    )
    assert repeated.status_code == 202
    assert repeated.json()["id"] == first["id"]
    rows = (
        await db_session.execute(
            select(DocumentPreview).where(DocumentPreview.project_id == project["id"])
        )
    ).scalars().all()
    assert len(rows) == 1

    other_user = await client.get(
        f"/previews/{first['id']}",
        cookies=auth_cookie(user_a),
    )
    assert other_user.status_code == 200
