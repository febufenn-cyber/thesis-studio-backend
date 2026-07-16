"""Submission Pack — one zip, checksummed manifest, honest review state."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile

import pytest
from httpx import AsyncClient

from app.models.project import Project
from app.models.source import Source
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio

_needs_soffice = pytest.mark.skipif(
    shutil.which("soffice") is None, reason="LibreOffice not installed"
)


async def _project(db_session, user) -> Project:
    project = Project(
        user_id=user.id, title="Pack Study", meta={"title": "Pack Study"}, front_matter=[],
        chapters=[{"number": 1, "title": "Intro", "blocks": [
            {"type": "paragraph", "runs": [{"text": "A paragraph of the thesis."}]}]}],
        works_cited=[],
    )
    db_session.add(project)
    await db_session.flush()
    source = Source(project_id=project.id, user_id=user.id, kind="book",
                    fields={"author": "Austen, Jane", "title": "[VERIFY]"},
                    raw_entry="Austen, Jane. Emma. J. Murray, 1815.",
                    parse_status="structured_with_review")
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@_needs_soffice
async def test_pack_downloads_with_honest_manifest(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    resp = await client.post(f"/projects/{project.id}/submission-pack", cookies=auth_cookie(user_a))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert resp.headers["X-Pack-State"] == "review"  # open findings -> honest state

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(zf.namelist())
    assert {"thesis.pdf", "integrity_report.json", "ai_use_statement.json",
            "ai_use_statement.txt", "quote_verification.json",
            "provenance_log.json", "manifest.json"} <= names

    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["state"] == "review"
    assert manifest["document_version"] == project.document_version
    # Checksums must match the actual files (integrity of the pack itself).
    for name, meta in manifest["files"].items():
        data = zf.read(name)
        assert hashlib.sha256(data).hexdigest() == meta["sha256"], name
        assert len(data) == meta["bytes"]
    # The PDF is real and the review render kept the loud marker.
    assert zf.read("thesis.pdf")[:5] == b"%PDF-"
    # Nothing got marked verified by packing.
    await db_session.refresh(project)
    assert manifest["verification"]["pass"] is False


@_needs_soffice
async def test_pack_owner_guarded(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = await _project(db_session, user_a)
    resp = await client.post(f"/projects/{project.id}/submission-pack", cookies=auth_cookie(user_b))
    assert resp.status_code == 404
