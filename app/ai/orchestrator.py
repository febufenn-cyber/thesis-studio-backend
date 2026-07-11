"""Durable grounded AI orchestration.

The orchestrator reads the canonical Project, compiles a bounded context, calls
a tool-disabled structured provider, validates the output, and stores inert
messages/proposals. It never applies a document command.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.ai.context import CompiledContext, ContextError, compile_context
from app.ai.memory import upsert_memory_updates
from app.ai.provider import (
    ClaudeRateLimitError,
    ClaudeSubprocessError,
    StructuredAIProvider,
    StructuredOutputError,
    get_structured_ai_provider,
)
from app.ai.proposal_engine import ProposalValidationError, validate_proposal_payload
from app.ai.schemas import AIScope
from app.ai.task_registry import get_task
from app.canonical.migrations import project_payload
from app.canonical.model import ThesisDocument
from app.db.session import AsyncSessionLocal
from app.models.ai_message import AIMessage
from app.models.ai_proposal import AIProposal
from app.models.ai_run import AIRun
from app.models.ai_thread import AIThread
from app.models.event import Event
from app.models.project import Project
from app.services.verification_service import verify_project


log = logging.getLogger(__name__)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _enrich_manifest(project: Project, scope: AIScope, compiled: CompiledContext) -> dict:
    """Add hashes for the exact canonical objects the run is allowed to reason about.

    Block and selection scopes use block hashes only so an unrelated change
    elsewhere in the chapter does not invalidate a still-relevant suggestion.
    Chapter/project scopes use chapter hashes because their reasoning depends on
    the complete structure and ordering of those chapters.
    """

    document = ThesisDocument.model_validate(project_payload(project))
    chapter_by_id = {str(chapter.id): chapter for chapter in document.chapters}
    block_by_id = {
        str(block.id): block
        for chapter in document.chapters
        for block in chapter.blocks
    }
    manifest = dict(compiled.manifest)
    chapter_ids = list(manifest.get("chapter_ids") or [])
    block_ids = list(manifest.get("block_ids") or [])

    if scope.type == "chapter" and scope.chapter_id:
        chapter = chapter_by_id.get(str(scope.chapter_id))
        if chapter:
            chapter_ids = [str(chapter.id)]
            block_ids = [str(block.id) for block in chapter.blocks]
    elif scope.type == "project":
        chapter_ids = [str(chapter.id) for chapter in document.chapters]
    elif scope.type in {"review", "source", "quote"}:
        block_ids = []

    manifest["chapter_ids"] = chapter_ids
    manifest["block_ids"] = block_ids
    manifest["block_hashes"] = {
        block_id: _hash(block_by_id[block_id].model_dump(mode="json"))
        for block_id in block_ids
        if block_id in block_by_id
    }
    manifest["chapter_hashes"] = (
        {
            chapter_id: _hash(chapter_by_id[chapter_id].model_dump(mode="json"))
            for chapter_id in chapter_ids
            if chapter_id in chapter_by_id
        }
        if scope.type in {"chapter", "project"}
        else {}
    )
    return manifest


async def _set_run_failure(run_id: UUID, message: str, *, retryable: bool) -> None:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(AIRun).where(AIRun.id == run_id))).scalar_one_or_none()
        if row is None:
            return
        row.status = "failed"
        row.error_message = message[:500]
        row.completed_at = datetime.now(timezone.utc)
        row.progress = {
            "stage": "failed",
            "message": message[:300],
            "retryable": retryable,
        }
        await db.commit()


async def run_grounded_ai(
    run_id: UUID,
    *,
    provider: StructuredAIProvider | None = None,
) -> None:
    provider = provider or get_structured_ai_provider()
    try:
        async with AsyncSessionLocal() as db:
            run = (await db.execute(select(AIRun).where(AIRun.id == run_id))).scalar_one_or_none()
            if run is None:
                raise ValueError("AI run no longer exists")
            if run.status == "succeeded":
                return
            if run.cancel_requested or run.status == "cancelled":
                run.status = "cancelled"
                run.completed_at = datetime.now(timezone.utc)
                run.progress = {"stage": "cancelled", "message": "Cancelled before provider call."}
                await db.commit()
                return

            project = (
                await db.execute(
                    select(Project).where(Project.id == run.project_id, Project.user_id == run.user_id)
                )
            ).scalar_one_or_none()
            thread = (
                await db.execute(
                    select(AIThread).where(
                        AIThread.id == run.thread_id,
                        AIThread.project_id == run.project_id,
                        AIThread.user_id == run.user_id,
                    )
                )
            ).scalar_one_or_none()
            request_message = (
                await db.execute(
                    select(AIMessage).where(
                        AIMessage.id == run.request_message_id,
                        AIMessage.thread_id == run.thread_id,
                        AIMessage.user_id == run.user_id,
                    )
                )
            ).scalar_one_or_none()
            if project is None or thread is None or request_message is None:
                raise ValueError("AI run ownership or request context is invalid")
            if project.document_version != run.requested_document_version:
                run.status = "stale"
                run.error_message = "Project changed before the AI task started."
                run.completed_at = datetime.now(timezone.utc)
                run.progress = {"stage": "stale", "message": run.error_message}
                await db.commit()
                return

            spec = get_task(run.task_mode)
            scope = AIScope.model_validate(run.scope or {})
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            run.attempts += 1
            run.error_message = None
            run.progress = {"stage": "compiling_context", "message": "Reading the selected canonical scope."}
            await db.commit()

            compiled = await compile_context(
                db,
                project,
                run.user_id,
                thread_id=thread.id,
                spec=spec,
                scope=scope,
                user_request=request_message.content,
            )
            manifest = _enrich_manifest(project, scope, compiled)
            context_hash = _hash(
                {"system": compiled.system_prompt, "user": compiled.user_prompt, "manifest": manifest}
            )
            run.context_manifest = manifest
            run.context_hash = context_hash
            request_message.context_manifest = manifest
            run.progress = {
                "stage": "provider",
                "message": "Analysing the selected scope without external tools.",
            }
            await db.commit()

            result = await provider.call(
                system_prompt=compiled.system_prompt,
                user_prompt=compiled.user_prompt,
                model=run.model,
                db=db,
                user_id=run.user_id,
                task_mode=run.task_mode,
            )

            await db.refresh(run)
            await db.refresh(project)
            if run.cancel_requested:
                run.status = "cancelled"
                run.completed_at = datetime.now(timezone.utc)
                run.progress = {
                    "stage": "cancelled",
                    "message": "Result discarded because cancellation was requested.",
                }
                await db.commit()
                return
            if project.document_version != run.requested_document_version:
                run.status = "stale"
                run.error_message = "Project changed while the AI task was running. Result was not published."
                run.completed_at = datetime.now(timezone.utc)
                run.progress = {"stage": "stale", "message": run.error_message}
                await db.commit()
                return

            output = result.output
            validated_proposal = None
            proposal_risk = spec.risk_level
            if output.proposal is not None:
                validated_proposal, proposal_risk = await validate_proposal_payload(
                    db,
                    project,
                    run.user_id,
                    spec,
                    output.proposal,
                    manifest,
                )

            structured = {
                "analysis": output.analysis,
                "research_queries": [item.model_dump(mode="json") for item in output.research_queries],
                "viva_questions": [item.model_dump(mode="json") for item in output.viva_questions],
                "proposal_id": None,
                "truth_notice": (
                    "Robofox verification proves internal traceability, not universal truth, "
                    "source credibility, originality or intellectual validity."
                ),
            }
            assistant = AIMessage(
                thread_id=thread.id,
                project_id=project.id,
                user_id=run.user_id,
                role="assistant",
                task_mode=run.task_mode,
                content=output.response_text,
                structured=structured,
                scope=run.scope,
                document_version=project.document_version,
                model=run.model,
                prompt_name=run.prompt_name,
                prompt_version=run.prompt_version,
                context_manifest=manifest,
                usage=result.usage,
            )
            db.add(assistant)
            await db.flush()

            proposal = None
            if validated_proposal is not None:
                before = await verify_project(db, project)
                proposal = AIProposal(
                    run_id=run.id,
                    project_id=project.id,
                    thread_id=thread.id,
                    user_id=run.user_id,
                    based_on_document_version=project.document_version,
                    task_mode=run.task_mode,
                    risk_level=proposal_risk,
                    status="open",
                    scope=run.scope,
                    rationale=validated_proposal.rationale,
                    explanation=validated_proposal.explanation,
                    operations=[item.model_dump(mode="json") for item in validated_proposal.operations],
                    evidence=validated_proposal.evidence.model_dump(mode="json"),
                    assumptions=validated_proposal.assumptions,
                    unresolved_requirements=validated_proposal.unresolved_requirements,
                    prompt_name=run.prompt_name,
                    prompt_version=run.prompt_version,
                    model=run.model,
                    context_manifest=manifest,
                    context_hash=context_hash,
                    verifier_before=before,
                )
                db.add(proposal)
                await db.flush()
                structured["proposal_id"] = str(proposal.id)
                assistant.structured = structured

            memories = await upsert_memory_updates(
                db,
                project,
                run.user_id,
                output.memory_updates,
                prompt_version=run.prompt_version,
                model=run.model,
            )
            thread.updated_at = datetime.now(timezone.utc)
            run.status = "succeeded"
            run.completed_at = datetime.now(timezone.utc)
            run.progress = {
                "stage": "complete",
                "message": "Analysis complete. Any document changes await your decision.",
                "assistant_message_id": str(assistant.id),
                "proposal_id": str(proposal.id) if proposal else None,
                "memory_ids": [str(memory.id) for memory in memories],
            }
            db.add(
                Event(
                    project_id=project.id,
                    user_id=run.user_id,
                    kind="grounded_ai_run_completed",
                    data={
                        "run_id": str(run.id),
                        "thread_id": str(thread.id),
                        "task_mode": run.task_mode,
                        "scope": run.scope,
                        "document_version": project.document_version,
                        "model": run.model,
                        "prompt_name": run.prompt_name,
                        "prompt_version": run.prompt_version,
                        "context_hash": context_hash,
                        "proposal_id": str(proposal.id) if proposal else None,
                        "injection_findings": manifest.get("injection_findings", []),
                    },
                )
            )
            await db.commit()
    except ContextError as exc:
        await _set_run_failure(run_id, str(exc), retryable=False)
        raise
    except ProposalValidationError as exc:
        await _set_run_failure(
            run_id,
            "The AI result was rejected by the academic safety validator: " + str(exc),
            retryable=False,
        )
        raise
    except StructuredOutputError as exc:
        await _set_run_failure(run_id, str(exc), retryable=True)
        raise
    except ClaudeRateLimitError:
        await _set_run_failure(
            run_id,
            "AI provider capacity was reached. Editing and export remain available.",
            retryable=True,
        )
        raise
    except ClaudeSubprocessError as exc:
        await _set_run_failure(run_id, str(exc), retryable=True)
        raise
    except Exception:
        log.exception("grounded AI run failed id=%s", run_id)
        await _set_run_failure(run_id, "Grounded AI task failed safely.", retryable=True)
        raise
