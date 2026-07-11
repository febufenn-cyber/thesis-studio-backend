"""Renderer-backed source schema and exact citation-resolution tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.user import User
from tests.conftest import auth_cookie


pytestmark = pytest.mark.asyncio


async def test_citation_schema_is_renderer_backed(
    client: AsyncClient,
    user_a: User,
) -> None:
    response = await client.get("/citation-source-kinds", cookies=auth_cookie(user_a))
    assert response.status_code == 200
    kinds = response.json()["kinds"]
    assert kinds["book"]["required"] == ["author", "title", "publisher", "year"]
    assert "doi_or_url" in kinds["journal_db"]["required"]
    assert kinds["web"]["required"] == ["title", "site", "url"]
    assert "unknown" not in kinds


async def test_same_surname_citation_requires_and_honors_exact_human_choice(
    client: AsyncClient,
    user_a: User,
) -> None:
    cookies = auth_cookie(user_a)
    created = await client.post(
        "/projects",
        json={"title": "Ambiguous Achebe citation", "format_profile": "mla_strict"},
        cookies=cookies,
    )
    assert created.status_code == 201
    project = created.json()
    seeded = await client.patch(
        f"/projects/{project['id']}/chapters",
        json={
            "expected_version": project["document_version"],
            "chapters": [
                {
                    "number": 1,
                    "title": "Introduction",
                    "blocks": [
                        {
                            "type": "paragraph",
                            "runs": [
                                {"text": "The narrative turns on communal judgment (Achebe 45)."}
                            ],
                        }
                    ],
                }
            ],
        },
        cookies=cookies,
    )
    assert seeded.status_code == 200
    chapter = seeded.json()["chapters"][0]
    block_id = chapter["blocks"][0]["id"]

    source_ids: list[str] = []
    for title, year in (("Things Fall Apart", "1958"), ("No Longer at Ease", "1960")):
        current = (await client.get(f"/projects/{project['id']}", cookies=cookies)).json()
        source = await client.post(
            f"/projects/{project['id']}/sources",
            json={
                "kind": "book",
                "fields": {
                    "author": "Achebe, Chinua",
                    "title": title,
                    "publisher": "Heinemann",
                    "year": year,
                },
                "verified": True,
                "verification_method": "manual",
                "expected_version": current["document_version"],
            },
            cookies=cookies,
        )
        assert source.status_code == 201
        source_ids.append(source.json()["id"])

    items = await client.get(
        f"/projects/{project['id']}/review-items",
        cookies=cookies,
    )
    assert items.status_code == 200
    ambiguous = next(
        item for item in items.json() if item["rule"] == "citation_ambiguous_source"
    )
    assert ambiguous["block_id"] == block_id
    assert "(Achebe 45)" in ambiguous["evidence"]["found"]
    assert all(source_id in ambiguous["evidence"]["expected"] for source_id in source_ids)

    current = (await client.get(f"/projects/{project['id']}", cookies=cookies)).json()
    resolution = await client.post(
        f"/projects/{project['id']}/citation-resolutions",
        json={
            "block_id": block_id,
            "raw_citation": "(Achebe 45)",
            "source_id": source_ids[0],
            "expected_version": current["document_version"],
        },
        cookies=cookies,
    )
    assert resolution.status_code == 200
    assert resolution.json()["source_id"] == source_ids[0]

    refreshed = await client.get(
        f"/projects/{project['id']}/review-items",
        cookies=cookies,
    )
    active_rules = {
        item["rule"]
        for item in refreshed.json()
        if item["status"] == "open" and item["block_id"] == block_id
    }
    assert "citation_ambiguous_source" not in active_rules
    # The selected source still needs to be placed in Works Cited; resolving the
    # ambiguity does not silently perform a different academic action.
    assert "cited_source_missing_from_wc" in active_rules
