"""Integrity Report — aggregation + fail-closed honesty (MF4)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.project import Project
from app.models.source import Source
from app.services.integrity_report import build_integrity_report
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


async def _project(db_session, user, *, chapters=None) -> Project:
    project = Project(
        user_id=user.id, title="IR", meta={"title": "Integrity"}, front_matter=[],
        chapters=chapters or [], works_cited=[],
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_report_aggregates_reference_status(db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    # A retracted source and a [VERIFY]-incomplete source.
    db_session.add(Source(
        project_id=project.id, user_id=user_a.id, kind="journal",
        fields={"author": "A", "title": "T", "container": "C", "volume": "1",
                "number": "2", "year": "2020", "pages": "1-2"},
        resolution_status="resolved", retraction_status="retracted", verified=True,
    ))
    db_session.add(Source(
        project_id=project.id, user_id=user_a.id, kind="book",
        fields={"author": "B", "title": "[VERIFY]"},
        resolution_status="unresolved",
    ))
    await db_session.commit()

    report = await build_integrity_report(db_session, project)
    refs = report["references"]["counts"]
    assert refs["total"] == 2
    assert refs["retracted"] == 1
    assert refs["verify_incomplete"] == 1
    # A retraction or an incomplete reference means the section is not ready.
    assert report["references"]["ready"] is False
    assert report["ready"] is False


async def test_report_counts_open_markers(db_session, user_a) -> None:
    project = await _project(db_session, user_a, chapters=[{
        "number": 1, "title": "C", "blocks": [
            {"type": "paragraph", "runs": [{"text": "x"}]},
            {"type": "marker", "kind": "VERIFY", "note": "check"},
        ],
    }])
    report = await build_integrity_report(db_session, project)
    assert report["open_markers"]["kinds"]["VERIFY"] == 1
    assert report["open_markers"]["ready"] is False


async def test_clean_project_is_ready_and_has_checksum(db_session, user_a) -> None:
    project = await _project(db_session, user_a, chapters=[{
        "number": 1, "title": "C", "blocks": [{"type": "paragraph", "runs": [{"text": "clean"}]}],
    }])
    report = await build_integrity_report(db_session, project)
    assert report["ready"] is True
    assert len(report["document_checksum"]) == 64
    assert "does not detect" in report["assertion"]
    assert "ai_provenance" in report


async def test_report_endpoint_owner_and_foreign(
    client: AsyncClient, db_session, user_a, user_b
) -> None:
    project = await _project(db_session, user_a)
    ok = await client.get(f"/projects/{project.id}/integrity-report", cookies=auth_cookie(user_a))
    assert ok.status_code == 200
    assert "document_checksum" in ok.json()

    forbidden = await client.get(
        f"/projects/{project.id}/integrity-report", cookies=auth_cookie(user_b)
    )
    assert forbidden.status_code == 404
