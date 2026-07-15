"""Retraction detection via Crossref update-to notices (docs/LLD.md 3.2)."""

from __future__ import annotations

import httpx
import pytest

from app.references.retraction import check_doi, status_from_retraction

pytestmark = pytest.mark.asyncio


def _client(payload: dict, status: int = 200) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload))
    )


async def test_retracted_doi_is_flagged() -> None:
    payload = {
        "message": {
            "type": "journal-article",
            "update-to": [{"type": "retraction", "DOI": "10.0/notice"}],
        }
    }
    async with _client(payload) as client:
        result = await check_doi(client, "10.0/paper")
    assert result == {
        "retracted": True,
        "kind": "retraction",
        "notice_doi": "10.0/notice",
        "source": "crossref",
    }
    assert status_from_retraction(result) == "retracted"


async def test_clean_doi_is_not_retracted() -> None:
    payload = {"message": {"type": "journal-article"}}
    async with _client(payload) as client:
        result = await check_doi(client, "10.0/clean")
    assert result == {"retracted": False, "source": "crossref"}
    assert status_from_retraction(result) == "none"


async def test_network_failure_is_unknown_not_clean() -> None:
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
        assert await check_doi(client, "10.0/x") is None
    assert status_from_retraction(None) is None
