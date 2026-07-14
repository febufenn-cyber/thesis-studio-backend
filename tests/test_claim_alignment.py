"""Claim–citation alignment (MF2) — advisory, opt-in, fail-closed."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.services.quote_verification_service as qv
from app.models.project import Project
from app.models.quote import Quote
from app.models.quote_verification import QuoteVerification
from app.models.source import Source
from app.verification.alignment import AlignmentResult, NoopAligner, get_claim_aligner
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


async def test_noop_aligner_is_default_and_unverifiable() -> None:
    aligner = get_claim_aligner()
    assert isinstance(aligner, NoopAligner)
    result = await aligner.align("premise", "hypothesis")
    assert result.status == "unverifiable"
    assert result.method == "none"


class _StubAligner:
    async def align(self, premise, hypothesis) -> AlignmentResult:
        return AlignmentResult(status="entailed", score=0.9, method="stub", rationale="ok")


class _BoomAligner:
    async def align(self, premise, hypothesis) -> AlignmentResult:
        raise RuntimeError("backend down")


async def _project_quote(db_session, user, text="a study of Mrs Dalloway"):
    project = Project(user_id=user.id, title="A", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.flush()
    source = Source(project_id=project.id, user_id=user.id, kind="book", fields={}, parse_status="imported")
    db_session.add(source)
    await db_session.flush()
    quote = Quote(source_id=source.id, project_id=project.id, user_id=user.id, text=text, page_or_loc="1")
    db_session.add(quote)
    await db_session.commit()
    await db_session.refresh(project)
    await db_session.refresh(quote)
    return project, quote


async def test_alignment_persists_and_stays_advisory(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    project, quote = await _project_quote(db_session, user_a)
    monkeypatch.setattr(qv, "get_claim_aligner", lambda: _StubAligner())

    response = await client.post(
        f"/projects/{project.id}/quotes/{quote.id}/verify-source",
        json={"source_text": "a study of Mrs Dalloway is offered here", "run_alignment": True},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "verified"  # verbatim result unchanged

    rows = list((await db_session.execute(
        select(QuoteVerification).where(QuoteVerification.quote_id == quote.id)
    )).scalars())
    kinds = {r.kind: r for r in rows}
    assert "alignment" in kinds
    assert kinds["alignment"].status == "entailed"
    # Human verify bit is never touched.
    await db_session.refresh(quote)
    assert quote.verified is False


async def test_alignment_backend_failure_is_unverifiable(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    project, quote = await _project_quote(db_session, user_a)
    monkeypatch.setattr(qv, "get_claim_aligner", lambda: _BoomAligner())
    response = await client.post(
        f"/projects/{project.id}/quotes/{quote.id}/verify-source",
        json={"source_text": "a study of Mrs Dalloway", "run_alignment": True},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    rows = list((await db_session.execute(
        select(QuoteVerification).where(
            QuoteVerification.quote_id == quote.id, QuoteVerification.kind == "alignment"
        )
    )).scalars())
    assert rows[0].status == "unverifiable"  # never entailed on failure


async def test_no_alignment_row_when_flag_off(client: AsyncClient, db_session, user_a) -> None:
    project, quote = await _project_quote(db_session, user_a)
    await client.post(
        f"/projects/{project.id}/quotes/{quote.id}/verify-source",
        json={"source_text": "a study of Mrs Dalloway"},
        cookies=auth_cookie(user_a),
    )
    rows = list((await db_session.execute(
        select(QuoteVerification).where(
            QuoteVerification.quote_id == quote.id, QuoteVerification.kind == "alignment"
        )
    )).scalars())
    assert rows == []
