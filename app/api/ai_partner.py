"""Phase 3 project-scoped grounded AI API.

Every route verifies project ownership before reading or scheduling AI work.
AI runs create inert messages/proposals; only the proposal-decision endpoint may
translate human-selected operations into the Phase 2 command service.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.capacity import (
    AICapacityExceeded,
    AIUnavailable,
    enforce_capacity,
    health_snapshot,
)
from app.ai.memory import link_legacy_session
from app.ai.proposal_engine import (
    ProposalStaleError,
    ProposalValidationError,
    decide_proposal,
)
from app.ai.schemas import AIRequest, AIScope, ProposalDecision
from app.ai.task_registry import get_task, model_for, public_task_catalog
from app.api.deps import CurrentUser, fetch_owned_project, fetch_owned_session
from app.db.deps import get_db
from app.models.ai_memory import AIMemory
from app.models.ai_message import AIMessage
from app.models.ai_proposal import AIProposal
from app.models.ai_run import AIRun
from app.models.ai_thread import AIThread
from app.models.event import Event
from app.models.research_candidate import ResearchCandidate
from app.models.source import Source
from app.services.editor_service import VersionConflict
from app.services.job_queue import enqueue_job


router = APIRouter(tags=["grounded-ai"])


_ALLOWED_SCOPES: dict[str, set[str]] = {
    "understand": {"block", "selection", "chapter", "review", "source", "quote"},
    "diagnose": {"block", "selection", "chapter", "review"},
    "plan": {"selection", "chapter"},
    "transform": {"block", "selection"},
    "challenge": {"block", "selection", "chapter"},
    "research": {"project", "chapter"},
    "coherence": {"project"},
    "viva": {"chapter", "project"},
    "memory_refresh": {"project", "chapter"},
}


class AIThreadCreate(BaseModel):
    title: str = Field("Robofox Scholar", min_length=2, max_length=240)
    scope: AIScope = Field(default_factory=AIScope)
    private: bool = True

    model_config = {"extra": "forbid"}


class AIPolicyUpdate(BaseModel):
    ai_enabled: bool | None = None
    allowed_modes: list[str] | None = None
    private_threads: bool | None = None
    supervisor_constraints: list[dict[str, Any]] | None = None
    disclosure_required: bool | None = None
    external_research: bool | None = None

    model_config = {"extra": "forbid"}


class LegacyLinkRequest(BaseModel):
    session_id: UUID


class CandidateCreate(BaseModel):
    query: str = Field("", max_length=2000)
    title: str = Field(..., min_length=2, max_length=2000)
    authors: list[str] = Field(default_factory=list, max_length=30)
    year: str | None = Field(None, max_length=20)
    source_type: str | None = Field(None, max_length=40)
    url: str | None = Field(None, max_length=4000)
    doi: str | None = Field(None, max_length=300)
    snippet: str | None = Field(None, max_length=6000)
    metadata_payload: dict[str, Any] = Field(default_factory=dict)
    thread_id: UUID | None = None

    model_config = {"extra": "forbid"}


class CandidateStatusUpdate(BaseModel):
    status: Literal["candidate", "metadata_confirmed", "accessed", "rejected"]


class CandidateAddSource(BaseModel):
    kind: str = Field(..., min_length=2, max_length=40)
    fields: dict[str, Any]
    raw_entry: str | None = Field(None, max_length=8000)

    model_config = {"extra": "forbid"}


def _thread_dict(row: AIThread) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "legacy_session_id": row.legacy_session_id,
        "title": row.title,
        "scope": row.scope,
        "private": row.private,
        "archived": row.archived,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _message_dict(row: AIMessage) -> dict:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "role": row.role,
        "task_mode": row.task_mode,
        "content": row.content,
        "structured": row.structured,
        "scope": row.scope,
        "document_version": row.document_version,
        "model": row.model,
        "prompt_name": row.prompt_name,
        "prompt_version": row.prompt_version,
        "context_manifest": row.context_manifest,
        "usage": row.usage,
        "created_at": row.created_at,
    }


def _run_dict(row: AIRun) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "thread_id": row.thread_id,
        "request_message_id": row.request_message_id,
        "client_request_id": row.client_request_id,
        "task_mode": row.task_mode,
        "result_type": row.result_type,
        "risk_level": row.risk_level,
        "scope": row.scope,
        "status": row.status,
        "requested_document_version": row.requested_document_version,
        "prompt_name": row.prompt_name,
        "prompt_version": row.prompt_version,
        "model": row.model,
        "context_manifest": row.context_manifest,
        "context_hash": row.context_hash,
        "progress": row.progress,
        "error_message": row.error_message,
        "cancel_requested": row.cancel_requested,
        "attempts": row.attempts,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


def _proposal_dict(row: AIProposal) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "thread_id": row.thread_id,
        "based_on_document_version": row.based_on_document_version,
        "task_mode": row.task_mode,
        "risk_level": row.risk_level,
        "status": row.status,
        "scope": row.scope,
        "rationale": row.rationale,
        "explanation": row.explanation,
        "operations": row.operations,
        "human_edited_operations": row.human_edited_operations,
        "evidence": row.evidence,
        "assumptions": row.assumptions,
        "unresolved_requirements": row.unresolved_requirements,
        "prompt_name": row.prompt_name,
        "prompt_version": row.prompt_version,
        "model": row.model,
        "context_manifest": row.context_manifest,
        "context_hash": row.context_hash,
        "selected_operation_indexes": row.selected_operation_indexes,
        "decision_note": row.decision_note,
        "rejection_reason": row.rejection_reason,
        "decision_by": row.decision_by,
        "decided_at": row.decided_at,
        "applied_command_id": row.applied_command_id,
        "verifier_before": row.verifier_before,
        "verifier_after": row.verifier_after,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _candidate_dict(row: ResearchCandidate) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "thread_id": row.thread_id,
        "query": row.query,
        "title": row.title,
        "authors": row.authors,
        "year": row.year,
        "source_type": row.source_type,
        "url": row.url,
        "doi": row.doi,
        "snippet": row.snippet,
        "metadata_payload": row.metadata_payload,
        "status": row.status,
        "added_source_id": row.added_source_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _owned_thread(
    db: AsyncSession, project_id: UUID, thread_id: UUID, user_id: UUID
) -> AIThread:
    row = (
        await db.execute(
            select(AIThread).where(
                AIThread.id == thread_id,
                AIThread.project_id == project_id,
                AIThread.user_id == user_id,
                AIThread.archived.is_(False),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="AI thread not found")
    return row


async def _owned_run(db: AsyncSession, project_id: UUID, run_id: UUID, user_id: UUID) -> AIRun:
    row = (
        await db.execute(
            select(AIRun).where(
                AIRun.id == run_id,
                AIRun.project_id == project_id,
                AIRun.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="AI run not found")
    return row


async def _owned_proposal(
    db: AsyncSession, project_id: UUID, proposal_id: UUID, user_id: UUID
) -> AIProposal:
    row = (
        await db.execute(
            select(AIProposal).where(
                AIProposal.id == proposal_id,
                AIProposal.project_id == project_id,
                AIProposal.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="AI proposal not found")
    return row


@router.get("/ai/tasks")
async def task_catalog(current_user: CurrentUser) -> list[dict]:
    del current_user
    return public_task_catalog()


@router.get("/projects/{project_id}/ai/policy")
async def get_ai_policy(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    return {"ai_enabled": project.ai_enabled, "policy": project.ai_policy or {}}


@router.patch("/projects/{project_id}/ai/policy")
async def update_ai_policy(
    project_id: UUID,
    body: AIPolicyUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    if body.external_research:
        raise HTTPException(
            status_code=409,
            detail=(
                "External research is not enabled in Phase 3. Robofox can formulate search queries, "
                "but it cannot claim to browse or verify sources."
            ),
        )
    policy = dict(project.ai_policy or {})
    if body.allowed_modes is not None:
        valid = {item["mode"] for item in public_task_catalog()}
        unknown = sorted(set(body.allowed_modes) - valid)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown task modes: {', '.join(unknown)}")
        policy["allowed_modes"] = body.allowed_modes
    if body.private_threads is not None:
        policy["private_threads"] = body.private_threads
    if body.supervisor_constraints is not None:
        policy["supervisor_constraints"] = body.supervisor_constraints
    if body.disclosure_required is not None:
        policy["disclosure_required"] = body.disclosure_required
    policy["external_research"] = False
    if body.ai_enabled is not None:
        project.ai_enabled = body.ai_enabled
    project.ai_policy = policy
    db.add(
        Event(
            project_id=project.id,
            user_id=current_user.id,
            kind="ai_policy_updated",
            data={"ai_enabled": project.ai_enabled, "policy": policy},
        )
    )
    await db.commit()
    return {"ai_enabled": project.ai_enabled, "policy": project.ai_policy}


@router.get("/projects/{project_id}/ai/health")
async def get_ai_health(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    return await health_snapshot(db, project, current_user.id)


@router.get("/projects/{project_id}/ai/threads")
async def list_threads(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await fetch_owned_project(db, project_id, current_user.id)
    rows = list(
        (
            await db.execute(
                select(AIThread)
                .where(
                    AIThread.project_id == project_id,
                    AIThread.user_id == current_user.id,
                    AIThread.archived.is_(False),
                )
                .order_by(AIThread.updated_at.desc())
            )
        ).scalars()
    )
    return [_thread_dict(row) for row in rows]


@router.post("/projects/{project_id}/ai/threads", status_code=201)
async def create_thread(
    project_id: UUID,
    body: AIThreadCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    private_required = bool((project.ai_policy or {}).get("private_threads", True))
    row = AIThread(
        project_id=project.id,
        user_id=current_user.id,
        title=body.title,
        scope=body.scope.model_dump(mode="json"),
        private=True if private_required else body.private,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _thread_dict(row)


@router.post("/projects/{project_id}/ai/link-legacy", status_code=201)
async def link_legacy(
    project_id: UUID,
    body: LegacyLinkRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    session = await fetch_owned_session(db, body.session_id, current_user.id)
    thread = await link_legacy_session(db, project, session, current_user.id)
    return _thread_dict(thread)


@router.get("/projects/{project_id}/ai/threads/{thread_id}/messages")
async def list_thread_messages(
    project_id: UUID,
    thread_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    await fetch_owned_project(db, project_id, current_user.id)
    await _owned_thread(db, project_id, thread_id, current_user.id)
    rows = list(
        (
            await db.execute(
                select(AIMessage)
                .where(
                    AIMessage.thread_id == thread_id,
                    AIMessage.project_id == project_id,
                    AIMessage.user_id == current_user.id,
                )
                .order_by(AIMessage.created_at.asc())
                .limit(limit)
            )
        ).scalars()
    )
    return [_message_dict(row) for row in rows]


@router.post("/projects/{project_id}/ai/runs", status_code=202)
async def create_ai_run(
    project_id: UUID,
    body: AIRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    if project.document_version != body.expected_document_version:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Project changed in another session. Reload before asking Robofox.",
                "expected_version": body.expected_document_version,
                "current_version": project.document_version,
            },
        )
    spec = get_task(body.task_mode)
    if body.scope.type not in _ALLOWED_SCOPES[spec.mode]:
        raise HTTPException(
            status_code=422,
            detail=f"Task mode {spec.mode!r} does not permit {body.scope.type!r} scope.",
        )

    if body.client_request_id:
        existing = (
            await db.execute(
                select(AIRun).where(
                    AIRun.project_id == project.id,
                    AIRun.user_id == current_user.id,
                    AIRun.client_request_id == body.client_request_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return _run_dict(existing)

    try:
        await enforce_capacity(db, project, current_user.id, spec)
    except AIUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AICapacityExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    if body.thread_id:
        thread = await _owned_thread(db, project.id, body.thread_id, current_user.id)
    else:
        thread = AIThread(
            project_id=project.id,
            user_id=current_user.id,
            title=f"{spec.mode.capitalize()} — Robofox Scholar",
            scope=body.scope.model_dump(mode="json"),
            private=bool((project.ai_policy or {}).get("private_threads", True)),
        )
        db.add(thread)
        await db.flush()

    user_message = AIMessage(
        thread_id=thread.id,
        project_id=project.id,
        user_id=current_user.id,
        role="user",
        task_mode=spec.mode,
        content=body.prompt,
        structured={},
        scope=body.scope.model_dump(mode="json"),
        document_version=project.document_version,
        prompt_name=spec.prompt_name,
        prompt_version=spec.prompt_version,
        context_manifest={},
        usage={},
    )
    db.add(user_message)
    await db.flush()
    run = AIRun(
        project_id=project.id,
        thread_id=thread.id,
        user_id=current_user.id,
        request_message_id=user_message.id,
        client_request_id=body.client_request_id,
        task_mode=spec.mode,
        result_type=spec.result_type,
        risk_level=spec.risk_level,
        scope=body.scope.model_dump(mode="json"),
        status="queued",
        requested_document_version=project.document_version,
        prompt_name=spec.prompt_name,
        prompt_version=spec.prompt_version,
        model=model_for(spec),
        progress={"stage": "queued", "message": "Waiting for the grounded AI worker."},
    )
    db.add(run)
    await db.flush()
    await enqueue_job(
        db,
        kind="ai_run",
        user_id=current_user.id,
        project_id=project.id,
        payload={"run_id": str(run.id), "project_id": str(project.id), "user_id": str(current_user.id)},
        max_attempts=3,
    )
    thread.updated_at = datetime.now(timezone.utc)
    db.add(
        Event(
            project_id=project.id,
            user_id=current_user.id,
            kind="grounded_ai_run_queued",
            data={
                "run_id": str(run.id),
                "thread_id": str(thread.id),
                "task_mode": spec.mode,
                "scope": run.scope,
                "document_version": project.document_version,
                "model": run.model,
                "prompt_version": run.prompt_version,
            },
        )
    )
    await db.commit()
    await db.refresh(run)
    return _run_dict(run)


@router.get("/projects/{project_id}/ai/runs")
async def list_ai_runs(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    await fetch_owned_project(db, project_id, current_user.id)
    rows = list(
        (
            await db.execute(
                select(AIRun)
                .where(AIRun.project_id == project_id, AIRun.user_id == current_user.id)
                .order_by(AIRun.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return [_run_dict(row) for row in rows]


@router.get("/projects/{project_id}/ai/runs/{run_id}")
async def get_ai_run(
    project_id: UUID,
    run_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await fetch_owned_project(db, project_id, current_user.id)
    return _run_dict(await _owned_run(db, project_id, run_id, current_user.id))


@router.post("/projects/{project_id}/ai/runs/{run_id}/cancel")
async def cancel_ai_run(
    project_id: UUID,
    run_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await fetch_owned_project(db, project_id, current_user.id)
    row = await _owned_run(db, project_id, run_id, current_user.id)
    if row.status in {"succeeded", "failed", "cancelled", "stale"}:
        return _run_dict(row)
    row.cancel_requested = True
    if row.status == "queued":
        row.status = "cancelled"
        row.completed_at = datetime.now(timezone.utc)
        row.progress = {"stage": "cancelled", "message": "Cancelled before execution."}
    await db.commit()
    await db.refresh(row)
    return _run_dict(row)


@router.get("/projects/{project_id}/ai/proposals")
async def list_proposals(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(None, alias="status"),
) -> list[dict]:
    await fetch_owned_project(db, project_id, current_user.id)
    query = select(AIProposal).where(
        AIProposal.project_id == project_id,
        AIProposal.user_id == current_user.id,
    )
    if status_filter:
        query = query.where(AIProposal.status == status_filter)
    rows = list((await db.execute(query.order_by(AIProposal.created_at.desc()).limit(300))).scalars())
    return [_proposal_dict(row) for row in rows]


@router.get("/projects/{project_id}/ai/proposals/{proposal_id}")
async def get_proposal(
    project_id: UUID,
    proposal_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await fetch_owned_project(db, project_id, current_user.id)
    return _proposal_dict(await _owned_proposal(db, project_id, proposal_id, current_user.id))


@router.post("/projects/{project_id}/ai/proposals/{proposal_id}/decision")
async def decide_ai_proposal(
    project_id: UUID,
    proposal_id: UUID,
    body: ProposalDecision,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    proposal = await _owned_proposal(db, project_id, proposal_id, current_user.id)
    try:
        decided, command = await decide_proposal(db, project, proposal, current_user.id, body)
    except VersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "expected_version": exc.expected, "current_version": exc.current},
        ) from exc
    except ProposalStaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProposalValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "proposal": _proposal_dict(decided),
        "command_id": command.id if command else None,
        "document_version": project.document_version,
    }


@router.get("/projects/{project_id}/ai/memories")
async def list_memories(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    include_stale: bool = False,
) -> list[dict]:
    await fetch_owned_project(db, project_id, current_user.id)
    query = select(AIMemory).where(
        AIMemory.project_id == project_id,
        AIMemory.user_id == current_user.id,
    )
    if not include_stale:
        query = query.where(AIMemory.stale.is_(False))
    rows = list((await db.execute(query.order_by(AIMemory.updated_at.desc()))).scalars())
    return [
        {
            "id": row.id,
            "scope_type": row.scope_type,
            "scope_key": row.scope_key,
            "kind": row.kind,
            "content": row.content,
            "based_on_document_version": row.based_on_document_version,
            "generated_by": row.generated_by,
            "prompt_version": row.prompt_version,
            "model": row.model,
            "stale": row.stale,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.get("/projects/{project_id}/research-candidates")
async def list_candidates(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await fetch_owned_project(db, project_id, current_user.id)
    rows = list(
        (
            await db.execute(
                select(ResearchCandidate)
                .where(
                    ResearchCandidate.project_id == project_id,
                    ResearchCandidate.user_id == current_user.id,
                )
                .order_by(ResearchCandidate.created_at.desc())
            )
        ).scalars()
    )
    return [_candidate_dict(row) for row in rows]


@router.post("/projects/{project_id}/research-candidates", status_code=201)
async def create_candidate(
    project_id: UUID,
    body: CandidateCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    if body.thread_id:
        await _owned_thread(db, project.id, body.thread_id, current_user.id)
    row = ResearchCandidate(
        project_id=project.id,
        user_id=current_user.id,
        thread_id=body.thread_id,
        query=body.query,
        title=body.title,
        authors=body.authors,
        year=body.year,
        source_type=body.source_type,
        url=body.url,
        doi=body.doi,
        snippet=body.snippet,
        metadata_payload=body.metadata_payload,
        status="candidate",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _candidate_dict(row)


@router.patch("/projects/{project_id}/research-candidates/{candidate_id}")
async def update_candidate_status(
    project_id: UUID,
    candidate_id: UUID,
    body: CandidateStatusUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await fetch_owned_project(db, project_id, current_user.id)
    row = (
        await db.execute(
            select(ResearchCandidate).where(
                ResearchCandidate.id == candidate_id,
                ResearchCandidate.project_id == project_id,
                ResearchCandidate.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Research candidate not found")
    allowed = {
        "candidate": {"metadata_confirmed", "rejected"},
        "metadata_confirmed": {"accessed", "rejected"},
        "accessed": {"rejected"},
        "rejected": {"candidate"},
        "added_registry": set(),
    }
    if body.status != row.status and body.status not in allowed.get(row.status, set()):
        raise HTTPException(status_code=409, detail=f"Cannot move candidate from {row.status} to {body.status}.")
    row.status = body.status
    await db.commit()
    await db.refresh(row)
    return _candidate_dict(row)


@router.post("/projects/{project_id}/research-candidates/{candidate_id}/add-source", status_code=201)
async def add_candidate_to_registry(
    project_id: UUID,
    candidate_id: UUID,
    body: CandidateAddSource,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    row = (
        await db.execute(
            select(ResearchCandidate).where(
                ResearchCandidate.id == candidate_id,
                ResearchCandidate.project_id == project.id,
                ResearchCandidate.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Research candidate not found")
    if row.status != "accessed":
        raise HTTPException(
            status_code=409,
            detail="Confirm that the candidate was accessed before adding it to the registry.",
        )
    if row.added_source_id:
        existing = (
            await db.execute(select(Source).where(Source.id == row.added_source_id))
        ).scalar_one_or_none()
        if existing:
            return {"candidate": _candidate_dict(row), "source_id": existing.id, "verified": existing.verified}
    source = Source(
        project_id=project.id,
        user_id=current_user.id,
        kind=body.kind,
        fields=body.fields,
        raw_entry=body.raw_entry,
        parse_status="structured_with_review",
        identifiers={
            "doi": row.doi,
            "url": row.url,
            "research_candidate_id": str(row.id),
        },
        verified=False,
        verify_note="Imported from a research candidate; human verification required.",
        verification_method=None,
    )
    db.add(source)
    await db.flush()
    row.added_source_id = source.id
    row.status = "added_registry"
    db.add(
        Event(
            project_id=project.id,
            user_id=current_user.id,
            kind="research_candidate_added_to_registry",
            data={
                "candidate_id": str(row.id),
                "source_id": str(source.id),
                "verified": False,
            },
        )
    )
    await db.commit()
    return {"candidate": _candidate_dict(row), "source_id": source.id, "verified": False}
