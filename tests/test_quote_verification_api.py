"""Quote-verification service + API (docs/LLD.md 3.3)."""

from __future__ import annotations

import base64

import pytest
from httpx import AsyncClient

from app.models.project import Project
from app.models.quote import Quote
from app.models.source import Source
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


async def _project_source_quote(db_session, user, quote_text: str, page: str = "42"):
    project = Project(user_id=user.id, title="QV", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.flush()
    source = Source(project_id=project.id, user_id=user.id, kind="book", fields={}, parse_status="imported")
    db_session.add(source)
    await db_session.flush()
    quote = Quote(
        source_id=source.id, project_id=project.id, user_id=user.id,
        text=quote_text, page_or_loc=page,
    )
    db_session.add(quote)
    await db_session.commit()
    await db_session.refresh(project)
    await db_session.refresh(quote)
    return project, quote


async def test_verify_exact_quote_is_verified(client: AsyncClient, db_session, user_a) -> None:
    project, quote = await _project_source_quote(db_session, user_a, "a study of Mrs Dalloway")
    response = await client.post(
        f"/projects/{project.id}/quotes/{quote.id}/verify-source",
        json={"source_text": "Here, a study of Mrs Dalloway is offered on the page."},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "verified"
    assert body["advisory"] is True
    # Human verify bit is never touched by verification.
    await db_session.refresh(quote)
    assert quote.verified is False


async def test_verify_missing_source_is_unverifiable(client: AsyncClient, db_session, user_a) -> None:
    project, quote = await _project_source_quote(db_session, user_a, "some quoted text")
    response = await client.post(
        f"/projects/{project.id}/quotes/{quote.id}/verify-source",
        json={},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    # No source provided -> unverifiable, never verified.
    assert response.json()["status"] == "unverifiable"


async def test_verify_html_source_via_base64(client: AsyncClient, db_session, user_a) -> None:
    project, quote = await _project_source_quote(db_session, user_a, "Real content here")
    html = b"<html><body><script>x()</script><p>Real content here on the page</p></body></html>"
    response = await client.post(
        f"/projects/{project.id}/quotes/{quote.id}/verify-source",
        json={
            "source_content_base64": base64.b64encode(html).decode(),
            "mime_type": "text/html",
        },
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


async def test_report_lists_results_and_is_owner_guarded(
    client: AsyncClient, db_session, user_a, user_b
) -> None:
    project, quote = await _project_source_quote(db_session, user_a, "a study of Mrs Dalloway")
    await client.post(
        f"/projects/{project.id}/quotes/{quote.id}/verify-source",
        json={"source_text": "a study of Mrs Dalloway"},
        cookies=auth_cookie(user_a),
    )
    report = await client.get(
        f"/projects/{project.id}/quote-verification/report", cookies=auth_cookie(user_a)
    )
    assert report.status_code == 200
    assert report.json()["counts"].get("verified") == 1

    forbidden = await client.get(
        f"/projects/{project.id}/quote-verification/report", cookies=auth_cookie(user_b)
    )
    assert forbidden.status_code == 404


async def test_verify_unknown_quote_404(client: AsyncClient, db_session, user_a) -> None:
    from uuid import uuid4
    project, _ = await _project_source_quote(db_session, user_a, "x")
    response = await client.post(
        f"/projects/{project.id}/quotes/{uuid4()}/verify-source",
        json={"source_text": "x"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 404
