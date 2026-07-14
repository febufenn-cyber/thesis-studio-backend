"""Provenance rollup counts block origins (docs/LLD.md 3.1)."""

from __future__ import annotations

import pytest

from app.models.project import Project
from app.provenance.rollup import build_rollup

pytestmark = pytest.mark.asyncio


def _para(text: str, origin: str | None = None) -> dict:
    block: dict = {"type": "paragraph", "runs": [{"text": text}]}
    if origin is not None:
        block["origin"] = origin
    return block


async def _project(db_session, user) -> Project:
    project = Project(
        user_id=user.id,
        title="Provenance",
        meta={"title": "Provenance Thesis"},
        front_matter=[],
        chapters=[
            {
                "number": 1,
                "title": "Introduction",
                "blocks": [
                    _para("a", "human"),
                    _para("b", "human"),
                    _para("c", "ai_proposal"),
                    _para("d", "ai_edited"),
                    _para("e"),  # no origin, no import -> unknown
                ],
            }
        ],
        works_cited=[],
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_rollup_counts_block_origins(db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    rollup = await build_rollup(db_session, project, document_version=project.document_version)
    assert rollup.total_blocks == 5
    assert rollup.origin_counts["human"] == 2
    assert rollup.origin_counts["ai_proposal"] == 1
    assert rollup.origin_counts["ai_edited"] == 1
    assert rollup.origin_counts["unknown"] == 1
    # ai_proposal + ai_edited
    assert rollup.ai_block_count == 2


async def test_rollup_without_proposals_is_unassisted(db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    rollup = await build_rollup(db_session, project, document_version=project.document_version)
    assert rollup.assisted is False
    assert rollup.accepted_proposals == 0
    payload = rollup.to_dict()
    assert payload["total_blocks"] == 5
    assert payload["ai_block_count"] == 2
