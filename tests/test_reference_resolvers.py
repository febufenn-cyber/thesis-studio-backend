"""Resolver adapters parse authority payloads offline (docs/LLD.md 3.2)."""

from __future__ import annotations

import httpx
import pytest

from app.references.resolvers.arxiv import ArxivResolver
from app.references.resolvers.crossref import CrossrefResolver
from app.references.resolvers.openalex import OpenAlexResolver
from app.references.resolvers.openlibrary import OpenLibraryResolver

pytestmark = pytest.mark.asyncio


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


_CROSSREF = {
    "message": {
        "type": "journal-article",
        "title": ["Modern Fiction"],
        "author": [{"given": "Virginia", "family": "Woolf"}],
        "container-title": ["The Common Reader"],
        "publisher": "Hogarth",
        "volume": "1",
        "issue": "3",
        "page": "150-158",
        "DOI": "10.1000/xyz123",
        "issued": {"date-parts": [[1925]]},
    }
}


async def test_crossref_parses_journal_article() -> None:
    async with _client(lambda r: httpx.Response(200, json=_CROSSREF)) as client:
        rec = await CrossrefResolver().resolve(client, "doi", "10.1000/xyz123")
    assert rec is not None and rec.matched
    assert rec.registry_kind == "journal"
    assert rec.fields["title"].value == "Modern Fiction"
    assert rec.fields["author"].value == "Woolf, Virginia"
    assert rec.fields["container"].value == "The Common Reader"
    assert rec.fields["number"].value == "3"
    assert rec.fields["year"].value == "1925"
    assert rec.fields["doi_or_url"].value == "10.1000/xyz123"


async def test_crossref_missing_returns_none() -> None:
    async with _client(lambda r: httpx.Response(404)) as client:
        assert await CrossrefResolver().resolve(client, "doi", "10.0/none") is None


async def test_crossref_transport_error_returns_none() -> None:
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    async with _client(boom) as client:
        assert await CrossrefResolver().resolve(client, "doi", "10.0/x") is None


_OPENALEX = {
    "type": "article",
    "title": "Attention Is All You Need",
    "authorships": [{"author": {"display_name": "Ashish Vaswani"}}],
    "primary_location": {"source": {"display_name": "NeurIPS", "host_organization_name": "NeurIPS"}},
    "biblio": {"volume": "30", "issue": "1", "first_page": "1", "last_page": "11"},
    "publication_year": 2017,
    "doi": "https://doi.org/10.1000/attn",
    "is_retracted": False,
}


async def test_openalex_parses_doi_work() -> None:
    async with _client(lambda r: httpx.Response(200, json=_OPENALEX)) as client:
        rec = await OpenAlexResolver().resolve(client, "doi", "10.1000/attn")
    assert rec is not None
    assert rec.fields["title"].value == "Attention Is All You Need"
    assert rec.fields["container"].value == "NeurIPS"
    assert rec.fields["pages"].value == "1-11"
    assert rec.fields["doi_or_url"].value == "10.1000/attn"


async def test_openalex_free_text_single_hit() -> None:
    payload = {"results": [_OPENALEX]}
    async with _client(lambda r: httpx.Response(200, json=payload)) as client:
        rec = await OpenAlexResolver().resolve(
            client, "freetext", "hash", {"query": "attention is all you need"}
        )
    assert rec is not None
    assert rec.fields["title"].value == "Attention Is All You Need"


_ARXIV_ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Attention Is All You Need</title>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <published>2017-06-12T00:00:00Z</published>
  </entry>
</feed>"""


async def test_arxiv_parses_atom() -> None:
    async with _client(lambda r: httpx.Response(200, text=_ARXIV_ATOM)) as client:
        rec = await ArxivResolver().resolve(client, "arxiv", "1706.03762")
    assert rec is not None
    assert rec.registry_kind == "web"
    assert rec.fields["title"].value == "Attention Is All You Need"
    assert rec.fields["site"].value == "arXiv"
    assert rec.fields["url"].value == "https://arxiv.org/abs/1706.03762"
    assert rec.fields["year"].value == "2017"
    assert rec.fields["author"].value == "Ashish Vaswani and Noam Shazeer"


_OPENLIB = {
    "ISBN:9780141187761": {
        "title": "Things Fall Apart",
        "authors": [{"name": "Chinua Achebe"}],
        "publishers": [{"name": "Penguin"}],
        "publish_date": "2001",
    }
}


async def test_openlibrary_parses_book() -> None:
    async with _client(lambda r: httpx.Response(200, json=_OPENLIB)) as client:
        rec = await OpenLibraryResolver().resolve(client, "isbn", "9780141187761")
    assert rec is not None
    assert rec.registry_kind == "book"
    assert rec.fields["title"].value == "Things Fall Apart"
    assert rec.fields["author"].value == "Chinua Achebe"
    assert rec.fields["publisher"].value == "Penguin"
    assert rec.fields["year"].value == "2001"
