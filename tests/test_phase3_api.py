"""Database-backed Phase 3 grounded AI workflow and isolation tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.orchestrator import run_grounded_ai
from app.ai.provider import ProviderResult
from app.ai.schemas import GroundedAIOutput
from app.models.ai_proposal import AIProposal
from app.models.ai_run import AIRun
from app.models.document_command import DocumentCommand
from app.models.project import Project
from app.models.quote import Quote
from app.models.source import Source
from app.models.user import User
from tests.conftest import auth_cookie


pytestmark = pytest.mark.asyncio


async def _project(client: AsyncClient, user: User, *, text: str = "The house represents authority.") -> dict:
    created = await client.post(
        "/projects",
        json={"title": "Grounded AI Thesis", "format_profile": "mla_strict"},
        cookies=auth_cookie(user),
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
                    "status": "in_progress",
                    "blocks": [
                        {"type": "paragraph", "runs": [{"text": text}]},
                        {
                            "type": "paragraph",
                            "runs": [{"text": "A second paragraph is outside the selected scope."}],
                        },
                    ],
                }
            ],
        },
        cookies=auth_cookie(user),
    )
    assert seeded.status_code == 200
    return seeded.json()


async def _run_request(
    client: AsyncClient,
    user: User,
    project: dict,
    *,
    mode: str = "transform",
    block_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    block_id = block_id or project["chapters"][0]["blocks"][0]["id"]
    response = await client.post(
        f"/projects/{project['id']}/ai/runs",
        json={
            "task_mode": mode,
            "prompt": "Strengthen the analytical connection without inventing evidence.",
            "scope": {"type": "block", "block_id": block_id},
            "expected_document_version": project["document_version"],
            "client_request_id": request_id,
        },
        cookies=auth_cookie(user),
    )
    assert response.status_code == 202, response.text
    return response.json()


class FakeProvider:
    def __init__(self, output: dict):
        self.output = GroundedAIOutput.model_validate(output)
        self.system_prompt = ""
        self.user_prompt = ""

    async def call(self, **kwargs):
        self.system_prompt = kwargs["system_prompt"]
        self.user_prompt = kwargs["user_prompt"]
        return ProviderResult(
            output=self.output,
            usage={
                "input_tokens": 100,
                "output_tokens": 50,
                "cached_input_tokens": 0,
                "estimated_cost_usd": None,
                "model": kwargs["model"],
            },
            raw_text="{}",
        )


async def _patch_worker_session(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr("app.ai.orchestrator.AsyncSessionLocal", factory)


async def test_run_creation_is_idempotent_scoped_and_cross_user_private(
    client: AsyncClient,
    user_a: User,
    user_b: User,
) -> None:
    project = await _project(client, user_a)
    request_id = f"ai-{uuid4()}"
    first = await _run_request(client, user_a, project, request_id=request_id)
    second = await _run_request(client, user_a, project, request_id=request_id)
    assert first["id"] == second["id"]
    assert first["status"] == "queued"
    assert first["scope"]["block_id"] == project["chapters"][0]["blocks"][0]["id"]

    attacker = await client.get(
        f"/projects/{project['id']}/ai/runs",
        cookies=auth_cookie(user_b),
    )
    assert attacker.status_code == 404


async def test_ai_proposal_is_inert_until_selected_human_acceptance(
    client: AsyncClient,
    user_a: User,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = await _project(client, user_a)
    block = project["chapters"][0]["blocks"][0]
    run = await _run_request(client, user_a, project, block_id=block["id"])
    provider = FakeProvider(
        {
            "response_text": "The paragraph names a symbol but does not connect it to the chapter claim.",
            "analysis": {
                "claim_present": True,
                "evidence_present": False,
                "analysis_present": False,
                "connection_to_chapter": "weak",
            },
            "proposal": {
                "rationale": "Make the analytical connection explicit without adding evidence.",
                "explanation": "This changes only the selected paragraph and preserves its claim.",
                "operations": [
                    {
                        "kind": "replace_runs",
                        "label": "Clarify analytical connection",
                        "reason": "Connect the symbol to inherited authority.",
                        "risk": "medium",
                        "payload": {
                            "block_id": block["id"],
                            "runs": [
                                {
                                    "text": "The house figures inherited authority by making domestic space carry the pressure of the past.",
                                    "italic": False,
                                }
                            ],
                        },
                    },
                    {
                        "kind": "insert_marker",
                        "label": "Request supporting evidence",
                        "reason": "The interpretive claim still needs textual evidence.",
                        "risk": "low",
                        "payload": {
                            "block_id": block["id"],
                            "kind": "EVIDENCE_NEEDED",
                            "note": "Add a verified primary-text passage supporting the claim.",
                        },
                    },
                ],
                "evidence": {"source_ids": [], "quote_ids": [], "evidence_types": ["critical_interpretation"], "missing": ["primary-text evidence"]},
                "assumptions": ["The chapter is analysing domestic space."],
                "unresolved_requirements": ["A supporting quotation remains necessary."],
            },
        }
    )
    await _patch_worker_session(monkeypatch, db_session)
    await run_grounded_ai(UUID(run["id"]), provider=provider)

    # Provider output is stored but the canonical paragraph remains untouched.
    unchanged = await client.get(
        f"/projects/{project['id']}/editor/chapters/{project['chapters'][0]['id']}",
        cookies=auth_cookie(user_a),
    )
    assert unchanged.json()["chapter"]["blocks"][0]["runs"][0]["text"] == "The house represents authority."

    proposals = await client.get(
        f"/projects/{project['id']}/ai/proposals",
        cookies=auth_cookie(user_a),
    )
    assert proposals.status_code == 200
    proposal = proposals.json()[0]
    assert proposal["status"] == "open"
    assert len(proposal["operations"]) == 2
    assert proposal["context_manifest"]["external_research_available"] is False
    assert "<untrusted_content" in provider.user_prompt

    accepted = await client.post(
        f"/projects/{project['id']}/ai/proposals/{proposal['id']}/decision",
        json={
            "action": "accept_selected",
            "selected_operation_indexes": [0],
            "expected_document_version": project["document_version"],
            "decision_note": "I accept the clearer connection but will find evidence myself.",
        },
        cookies=auth_cookie(user_a),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["proposal"]["status"] == "partially_accepted"

    changed = await client.get(
        f"/projects/{project['id']}/editor/chapters/{project['chapters'][0]['id']}",
        cookies=auth_cookie(user_a),
    )
    blocks = changed.json()["chapter"]["blocks"]
    assert blocks[0]["runs"][0]["text"].startswith("The house figures inherited authority")
    assert all(item["type"] != "marker" for item in blocks)
    commands = list(
        (
            await db_session.execute(
                select(DocumentCommand).where(DocumentCommand.project_id == UUID(project["id"]))
            )
        ).scalars()
    )
    assert len(commands) == 1
    assert commands[0].summary.startswith("Accept 1 Robofox Scholar")


async def test_changed_target_makes_proposal_stale(
    client: AsyncClient,
    user_a: User,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = await _project(client, user_a)
    block = project["chapters"][0]["blocks"][0]
    run = await _run_request(client, user_a, project, block_id=block["id"])
    provider = FakeProvider(
        {
            "response_text": "A bounded revision is available.",
            "proposal": {
                "rationale": "Clarify the sentence.",
                "explanation": "Only the selected block changes.",
                "operations": [
                    {
                        "kind": "replace_runs",
                        "label": "Clarify",
                        "reason": "Improve precision.",
                        "payload": {
                            "block_id": block["id"],
                            "runs": [{"text": "The house materialises inherited authority."}],
                        },
                    }
                ],
                "evidence": {},
            },
        }
    )
    await _patch_worker_session(monkeypatch, db_session)
    await run_grounded_ai(UUID(run["id"]), provider=provider)
    proposal = (
        await client.get(f"/projects/{project['id']}/ai/proposals", cookies=auth_cookie(user_a))
    ).json()[0]

    edited = await client.post(
        f"/projects/{project['id']}/editor/commands",
        json={
            "command_type": "update_block_text",
            "payload": {"block_id": block["id"], "text": "The student changed this paragraph first."},
            "expected_document_version": project["document_version"],
        },
        cookies=auth_cookie(user_a),
    )
    assert edited.status_code == 200
    decision = await client.post(
        f"/projects/{project['id']}/ai/proposals/{proposal['id']}/decision",
        json={
            "action": "accept_all",
            "expected_document_version": edited.json()["document_version"],
            "decision_note": "Apply it.",
        },
        cookies=auth_cookie(user_a),
    )
    assert decision.status_code == 409
    assert "changed" in str(decision.json()["detail"]).lower()


async def test_verified_quote_text_is_inserted_from_registry_not_provider(
    client: AsyncClient,
    user_a: User,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = await _project(client, user_a)
    block = project["chapters"][0]["blocks"][0]
    source = Source(
        project_id=UUID(project["id"]),
        user_id=user_a.id,
        kind="book",
        fields={"author": "Achebe, Chinua", "title": "Things Fall Apart", "publisher": "Heinemann", "year": "1958"},
        verified=True,
        parse_status="fully_structured",
    )
    db_session.add(source)
    await db_session.flush()
    quote = Quote(
        source_id=source.id,
        project_id=UUID(project["id"]),
        user_id=user_a.id,
        page_or_loc="13",
        text="Okonkwo was well known throughout the nine villages and even beyond.",
        method="manual",
        verified=True,
    )
    db_session.add(quote)
    await db_session.commit()

    run = await _run_request(client, user_a, project, block_id=block["id"])
    provider = FakeProvider(
        {
            "response_text": "The verified primary-text evidence can be placed after the paragraph.",
            "proposal": {
                "rationale": "Use registered primary-text evidence.",
                "explanation": "The quotation wording will be inserted by the server from the verified registry.",
                "operations": [
                    {
                        "kind": "add_verified_quote",
                        "label": "Insert verified quotation",
                        "reason": "Support the claim with registered primary-text evidence.",
                        "payload": {
                            "chapter_id": project["chapters"][0]["id"],
                            "after_block_id": block["id"],
                            "quote_id": str(quote.id),
                            "citation": "Achebe 13",
                        },
                    }
                ],
                "evidence": {
                    "source_ids": [str(source.id)],
                    "quote_ids": [str(quote.id)],
                    "evidence_types": ["direct_quotation"],
                    "missing": [],
                },
            },
        }
    )
    await _patch_worker_session(monkeypatch, db_session)
    await run_grounded_ai(UUID(run["id"]), provider=provider)
    proposal = (
        await client.get(f"/projects/{project['id']}/ai/proposals", cookies=auth_cookie(user_a))
    ).json()[0]
    accepted = await client.post(
        f"/projects/{project['id']}/ai/proposals/{proposal['id']}/decision",
        json={
            "action": "accept_all",
            "expected_document_version": project["document_version"],
            "decision_note": "I checked the exact quotation and location.",
        },
        cookies=auth_cookie(user_a),
    )
    assert accepted.status_code == 200, accepted.text
    chapter = (
        await client.get(
            f"/projects/{project['id']}/editor/chapters/{project['chapters'][0]['id']}",
            cookies=auth_cookie(user_a),
        )
    ).json()["chapter"]
    inserted = next(item for item in chapter["blocks"] if item["type"] == "block_quote")
    assert inserted["text"] == quote.text
    assert inserted["quote_id"] == str(quote.id)


async def test_ai_kill_switch_preserves_deterministic_workspace(
    client: AsyncClient,
    user_a: User,
) -> None:
    project = await _project(client, user_a)
    disabled = await client.patch(
        f"/projects/{project['id']}/ai/policy",
        json={"ai_enabled": False},
        cookies=auth_cookie(user_a),
    )
    assert disabled.status_code == 200
    run = await client.post(
        f"/projects/{project['id']}/ai/runs",
        json={
            "task_mode": "transform",
            "prompt": "Rewrite this paragraph.",
            "scope": {"type": "block", "block_id": project["chapters"][0]["blocks"][0]["id"]},
            "expected_document_version": project["document_version"],
        },
        cookies=auth_cookie(user_a),
    )
    assert run.status_code == 503
    health = await client.get(
        f"/projects/{project['id']}/ai/health",
        cookies=auth_cookie(user_a),
    )
    assert health.json()["degraded_mode"] is True
    assert health.json()["deterministic_workspace_available"] is True
    editor = await client.get(
        f"/projects/{project['id']}/editor/structure",
        cookies=auth_cookie(user_a),
    )
    assert editor.status_code == 200


async def test_research_candidate_cannot_become_verified_automatically(
    client: AsyncClient,
    user_a: User,
    db_session: AsyncSession,
) -> None:
    project = await _project(client, user_a)
    candidate = await client.post(
        f"/projects/{project['id']}/research-candidates",
        json={
            "query": "postcolonial domestic space scholarship",
            "title": "Space and Colonial Power",
            "authors": ["A. Scholar"],
            "year": "2024",
            "source_type": "journal",
            "doi": "10.1234/example",
            "snippet": "Discovery snippet is not evidence.",
        },
        cookies=auth_cookie(user_a),
    )
    assert candidate.status_code == 201
    candidate_id = candidate.json()["id"]
    for next_status in ("metadata_confirmed", "accessed"):
        moved = await client.patch(
            f"/projects/{project['id']}/research-candidates/{candidate_id}",
            json={"status": next_status},
            cookies=auth_cookie(user_a),
        )
        assert moved.status_code == 200
    added = await client.post(
        f"/projects/{project['id']}/research-candidates/{candidate_id}/add-source",
        json={
            "kind": "journal",
            "fields": {
                "author": "Scholar, A.",
                "title": "Space and Colonial Power",
                "container": "Journal of Example Studies",
                "volume": "1",
                "number": "1",
                "year": "2024",
                "pages": "1-20",
            },
            "raw_entry": "Scholar, A. ‘Space and Colonial Power.’ ...",
        },
        cookies=auth_cookie(user_a),
    )
    assert added.status_code == 201
    assert added.json()["verified"] is False
    source = (
        await db_session.execute(select(Source).where(Source.id == UUID(added.json()["source_id"])))
    ).scalar_one()
    assert source.verified is False
    assert source.parse_status == "structured_with_review"
