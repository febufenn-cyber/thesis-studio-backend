"""resolve_one + apply_to_source write-back under never-guess (docs/LLD.md 3.2)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.models.project import Project
from app.models.source import Source
from app.models.source_field_provenance import SourceFieldProvenance
from app.references.service import apply_to_source, resolve_one
from app.renderers.field_schema import missing_required

pytestmark = pytest.mark.asyncio

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

_OPENALEX = {
    "type": "article",
    "title": "Modern Fiction",
    "authorships": [{"author": {"display_name": "Virginia Woolf"}}],
    "primary_location": {"source": {"display_name": "The Common Reader"}},
    "biblio": {"volume": "1", "issue": "3", "first_page": "150", "last_page": "158"},
    "publication_year": 1925,
    "doi": "https://doi.org/10.1000/xyz123",
}


def _handler(request):
    host = request.url.host
    if host == "api.crossref.org":
        return httpx.Response(200, json=_CROSSREF)
    if host == "api.openalex.org":
        return httpx.Response(200, json=_OPENALEX)
    return httpx.Response(404)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


async def _journal_source(db_session, user) -> Source:
    project = Project(user_id=user.id, title="Resolve", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.flush()
    source = Source(
        project_id=project.id,
        user_id=user.id,
        kind="journal",
        fields={k: "[VERIFY]" for k in
                ("author", "title", "container", "volume", "number", "year", "pages")},
        parse_status="imported",
    )
    db_session.add(source)
    await db_session.flush()
    return source


async def test_apply_fills_missing_fields_and_records_provenance(db_session, user_a) -> None:
    source = await _journal_source(db_session, user_a)
    async with _client() as client:
        record = await resolve_one(db_session, "10.1000/xyz123", client=client)
    assert record.status == "resolved"

    applied = await apply_to_source(db_session, source, record)
    assert set(applied) >= {"title", "author", "container", "volume", "number", "year", "pages"}
    assert source.fields["title"] == "Modern Fiction"
    assert source.fields["author"] == "Woolf, Virginia"
    assert missing_required("journal", source.fields) == []
    # Never auto-verified; provenance recorded; method stamped.
    assert source.verified is False
    assert source.verification_method == "resolver"
    assert source.resolution_status == "resolved"

    prov = list(
        (await db_session.execute(
            select(SourceFieldProvenance).where(SourceFieldProvenance.source_id == source.id)
        )).scalars()
    )
    assert {p.field_name for p in prov} == set(applied)
    assert all(p.applied for p in prov)


async def test_low_confidence_leaves_verify_placeholder(db_session, user_a) -> None:
    source = await _journal_source(db_session, user_a)
    async with _client() as client:
        record = await resolve_one(db_session, "10.1000/xyz123", client=client)
    # pages (crossref 0.85, boosted by agreement to ~0.87) never clears a 0.99
    # gate, so it stays a [VERIFY] placeholder — never guessed.
    applied = await apply_to_source(db_session, source, record, min_confidence=0.99)
    assert "pages" not in applied
    assert source.fields["pages"] == "[VERIFY]"


async def test_resolve_one_uses_cache_on_second_call(db_session, user_a) -> None:
    calls = {"n": 0}

    def counting_handler(request):
        calls["n"] += 1
        return _handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(counting_handler))
    async with client:
        first = await resolve_one(db_session, "10.1000/xyz123", client=client)
        after_first = calls["n"]
        second = await resolve_one(db_session, "10.1000/xyz123", client=client)
    assert first.id == second.id
    # Second call served from the DB cache — no further HTTP calls.
    assert calls["n"] == after_first
