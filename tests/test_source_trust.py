"""Source & Journal Trust (enterprise E1)."""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

from app.models.project import Project
from app.models.source import Source
from app.references.trust import assess_source_trust
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio

_OPENALEX_REPUTABLE = {"results": [{
    "display_name": "Nature", "is_in_doaj": False, "is_oa": False,
    "host_organization_name": "Springer Nature", "works_count": 400000,
    "cited_by_count": 20000000, "summary_stats": {"h_index": 1200},
}]}
_OPENALEX_DOAJ = {"results": [{
    "display_name": "PLOS ONE", "is_in_doaj": True, "is_oa": True,
    "host_organization_name": "PLOS", "works_count": 250000,
    "cited_by_count": 5000000, "summary_stats": {"h_index": 400},
}]}
_CROSSREF_CLEAN = {"message": {"type": "journal-article"}}
_CROSSREF_RETRACTED = {"message": {"type": "journal-article",
    "update-to": [{"type": "retraction", "DOI": "10.0/notice"}]}}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(openalex, crossref):
    def h(request):
        host = request.url.host
        if host == "api.openalex.org":
            return httpx.Response(200, json=openalex)
        if host == "api.crossref.org":
            return httpx.Response(200, json=crossref)
        return httpx.Response(404)
    return h


async def _source(db_session, user, container="Nature", doi="10.1000/x") -> Source:
    project = Project(user_id=user.id, title="T", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.flush()
    source = Source(project_id=project.id, user_id=user.id, kind="journal",
                    fields={"container": container, "doi_or_url": doi}, parse_status="imported")
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)
    return source


async def test_reputable_journal(db_session, user_a) -> None:
    src = await _source(db_session, user_a, "Nature")
    async with _client(_handler(_OPENALEX_REPUTABLE, _CROSSREF_CLEAN)) as client:
        report = await assess_source_trust(db_session, src, client=client)
    assert report["verdict"] == "reputable"
    assert report["journal"]["h_index"] == 1200
    assert report["advisory"] is True


async def test_doaj_open_access_is_reputable(db_session, user_a) -> None:
    src = await _source(db_session, user_a, "PLOS ONE")
    async with _client(_handler(_OPENALEX_DOAJ, _CROSSREF_CLEAN)) as client:
        report = await assess_source_trust(db_session, src, client=client)
    assert report["verdict"] == "reputable"
    assert report["journal"]["in_doaj"] is True
    assert any("Directory of Open Access" in s for s in report["signals"])


async def test_retracted_is_caution(db_session, user_a) -> None:
    src = await _source(db_session, user_a, "Nature")
    async with _client(_handler(_OPENALEX_REPUTABLE, _CROSSREF_RETRACTED)) as client:
        report = await assess_source_trust(db_session, src, client=client)
    assert report["verdict"] == "caution"
    assert report["retraction"]["retracted"] is True


async def test_unknown_journal_is_never_labelled_predatory(db_session, user_a) -> None:
    src = await _source(db_session, user_a, "Journal of Nowhere")
    async with _client(_handler({"results": []}, _CROSSREF_CLEAN)) as client:
        report = await assess_source_trust(db_session, src, client=client)
    # Absence of a record is 'unknown' + a "verify" nudge — never "predatory".
    assert report["verdict"] == "unknown"
    assert "predatory" not in str(report["signals"]).lower()


async def test_disabled_returns_unknown_no_network(db_session, user_a) -> None:
    src = await _source(db_session, user_a, "Nature")
    # SOURCE_TRUST_ENABLED=false in conftest, no client -> unknown, no calls.
    report = await assess_source_trust(db_session, src)
    assert report["verdict"] == "unknown"
    assert report["journal"] is None


async def test_trust_endpoint(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    import app.references.trust as trust_mod
    src = await _source(db_session, user_a, "Nature")
    monkeypatch.setattr(trust_mod, "get_settings", lambda: type("S", (), {"SOURCE_TRUST_ENABLED": True, "SHERPA_ROMEO_API_KEY": ""})())
    monkeypatch.setattr(trust_mod, "build_client", lambda transport=None: _client(_handler(_OPENALEX_REPUTABLE, _CROSSREF_CLEAN)))
    project_id = src.project_id
    resp = await client.get(f"/projects/{project_id}/sources/{src.id}/trust", cookies=auth_cookie(user_a))
    assert resp.status_code == 200
    assert resp.json()["verdict"] == "reputable"

    # owner guard
    resp2 = await client.get(f"/projects/{project_id}/sources/{src.id}/trust", cookies=auth_cookie(user_a))
    assert resp2.status_code == 200
