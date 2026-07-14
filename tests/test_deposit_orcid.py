"""External deposit + ORCID (MF3)."""

from __future__ import annotations

import tempfile

import httpx
import pytest
from httpx import AsyncClient

import app.api.deposits as deposits_api
import app.services.deposit_service as ds
from app.integrations.deposit import DepositError, DepositMeta, DepositResult
from app.integrations.orcid import is_well_formed
from app.models.export import Export
from app.models.project import Project
from app.services.deposit_service import create_deposit
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


class _FakeTarget:
    name = "zenodo"

    def __init__(self, fail_at: str | None = None):
        self.calls: list[str] = []
        self.fail_at = fail_at

    async def create_draft(self, meta: DepositMeta) -> DepositResult:
        self.calls.append("create_draft")
        if self.fail_at == "create_draft":
            raise DepositError("draft failed")
        return DepositResult(remote_id="R1")

    async def upload_file(self, remote_id, path, filename, media_type) -> DepositResult:
        self.calls.append("upload_file")
        if self.fail_at == "upload_file":
            raise DepositError("upload failed")
        return DepositResult(remote_id=remote_id)

    async def publish(self, remote_id) -> DepositResult:
        self.calls.append("publish")
        if self.fail_at == "publish":
            raise DepositError("publish failed")
        return DepositResult(remote_id=remote_id, doi="10.5281/zenodo.999", landing_url="https://z/records/999")


async def _project_export(db_session, user):
    project = Project(user_id=user.id, title="Dep", meta={"title": "Dep", "candidate": {"name": "Jane Doe"}},
                      front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.flush()
    export = Export(project_id=project.id, user_id=user.id, format="pdf", status="ready", storage_key="k/1.pdf")
    db_session.add(export)
    await db_session.commit()
    await db_session.refresh(project)
    await db_session.refresh(export)
    return project, export


def _mock_storage(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(b"%PDF-1.4 fake")
    tmp.close()

    class _Storage:
        async def download_to_temp(self, key):
            return tmp.name

    monkeypatch.setattr(ds, "get_storage_service", lambda: _Storage())


async def test_deposit_state_machine_publishes(db_session, user_a, monkeypatch) -> None:
    project, export = await _project_export(db_session, user_a)
    _mock_storage(monkeypatch)
    target = _FakeTarget()
    deposit = await create_deposit(db_session, project, export, user_a.id, target)
    assert target.calls == ["create_draft", "upload_file", "publish"]
    assert deposit.status == "published"
    assert deposit.doi == "10.5281/zenodo.999"


async def test_deposit_failure_marks_failed(db_session, user_a, monkeypatch) -> None:
    project, export = await _project_export(db_session, user_a)
    _mock_storage(monkeypatch)
    deposit = await create_deposit(db_session, project, export, user_a.id, _FakeTarget(fail_at="publish"))
    assert deposit.status == "failed"
    assert deposit.doi is None
    assert "publish failed" in deposit.error_message


async def test_deposit_not_ready_raises(db_session, user_a) -> None:
    project, export = await _project_export(db_session, user_a)
    export.status = "queued"
    with pytest.raises(ValueError):
        await create_deposit(db_session, project, export, user_a.id, _FakeTarget())


async def test_deposit_endpoint_fails_closed_without_token(client: AsyncClient, db_session, user_a) -> None:
    project, export = await _project_export(db_session, user_a)
    # ZENODO_TOKEN unset by default -> 503, no network.
    response = await client.post(
        f"/projects/{project.id}/deposits",
        json={"export_id": str(export.id), "target": "zenodo"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 503


async def test_orcid_link_verifies_and_stores(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    monkeypatch.setattr(
        deposits_api, "build_client",
        lambda transport=None: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))),
    )
    response = await client.post(
        "/orcid", json={"orcid": "0000-0002-1825-0097"}, cookies=auth_cookie(user_a)
    )
    assert response.status_code == 200
    assert response.json()["verified"] is True
    await db_session.refresh(user_a)
    assert user_a.orcid == "0000-0002-1825-0097"


async def test_orcid_malformed_is_422(client: AsyncClient, user_a) -> None:
    response = await client.post("/orcid", json={"orcid": "not-an-orcid"}, cookies=auth_cookie(user_a))
    assert response.status_code == 422
    assert is_well_formed("0000-0002-1825-0097") and not is_well_formed("bad")
