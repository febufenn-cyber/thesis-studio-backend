"""Semantic proposal validation and human-controlled application.

AI proposals are inert records. Only this module can translate selected,
human-approved operations into the Phase 2 command engine.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import AIOperation, AIProposalPayload, ProposalDecision
from app.ai.settings import get_ai_settings
from app.ai.task_registry import TaskSpec
from app.canonical.migrations import project_payload
from app.canonical.model import MARKER_KINDS, HeadingBlock, ParagraphBlock, ThesisDocument
from app.models.ai_memory import AIMemory
from app.models.ai_proposal import AIProposal
from app.models.document_command import DocumentCommand
from app.models.event import Event
from app.models.project import Project
from app.models.quote import Quote
from app.models.source import Source
from app.services.editor_service import VersionConflict, apply_project_command
from app.services.registry_scope import active_revision_rows
from app.services.review_service import sync_review_items
from app.services.verification_service import verify_project


class ProposalValidationError(RuntimeError):
    pass


class ProposalStaleError(RuntimeError):
    pass


_RISK_RANK = {"low": 0, "medium": 1, "high": 2}
# Derived from the canonical model so the proposal validator and MarkerBlock.kind
# can never disagree. Previously this was a hand-maintained set that included
# kinds (STRUCTURE_REVIEW, EVIDENCE_NEEDED) the model rejected, so an accepted
# proposal using them crashed when the marker block was built at apply time.
_ALLOWED_MARKERS = MARKER_KINDS
_LONG_QUOTED_TEXT = re.compile(r"[\"“][^\"”\n]{20,}[\"”]")


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _document(project: Project) -> ThesisDocument:
    return ThesisDocument.model_validate(project_payload(project))


def _document_indexes(document: ThesisDocument):
    chapters = {str(chapter.id): chapter for chapter in document.chapters}
    blocks: dict[str, tuple[Any, int, Any]] = {}
    for chapter in document.chapters:
        for index, block in enumerate(chapter.blocks):
            blocks[str(block.id)] = (chapter, index, block)
    return chapters, blocks


def _operation_text(operation: AIOperation) -> str:
    payload = operation.payload
    if isinstance(payload.get("text"), str):
        return payload["text"]
    return "".join(str(run.get("text", "")) for run in payload.get("runs", []) if isinstance(run, dict))


def _reject_unregistered_direct_quote(operation: AIOperation) -> None:
    text = _operation_text(operation)
    if _LONG_QUOTED_TEXT.search(text):
        raise ProposalValidationError(
            "AI prose operations cannot introduce long direct-quotation text. "
            "Use add_verified_quote with a human-verified quote_id or add a QUOTE_NEEDED marker."
        )


def _maximum_risk(operations: list[AIOperation], default: str) -> str:
    risk = default
    for operation in operations:
        candidate = "high" if operation.kind == "move_block" else operation.risk
        if _RISK_RANK[candidate] > _RISK_RANK[risk]:
            risk = candidate
    return risk


async def validate_proposal_payload(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    spec: TaskSpec,
    proposal: AIProposalPayload,
    context_manifest: dict,
) -> tuple[AIProposalPayload, str]:
    settings = get_ai_settings()
    if spec.result_type != "proposal" and proposal.operations:
        raise ProposalValidationError(
            f"Task mode {spec.mode!r} is advisory and may not emit document operations."
        )
    if len(proposal.operations) > settings.max_proposal_operations:
        raise ProposalValidationError("Proposal exceeds the server operation limit.")

    document = _document(project)
    chapters, blocks = _document_indexes(document)
    scoped_blocks = set(context_manifest.get("block_ids") or [])
    scoped_chapters = set(context_manifest.get("chapter_ids") or [])
    included_sources = {UUID(value) for value in context_manifest.get("source_ids") or []}
    included_quotes = {UUID(value) for value in context_manifest.get("quote_ids") or []}
    verified_source_ids = {UUID(value) for value in context_manifest.get("verified_source_ids") or []}
    verified_quote_ids = {UUID(value) for value in context_manifest.get("verified_quote_ids") or []}

    evidence_sources = set(proposal.evidence.source_ids)
    evidence_quotes = set(proposal.evidence.quote_ids)
    if not evidence_sources.issubset(included_sources):
        raise ProposalValidationError("Proposal referenced a source outside its compiled context.")
    if not evidence_quotes.issubset(included_quotes):
        raise ProposalValidationError("Proposal referenced a quotation outside its compiled context.")

    all_sources = list(
        (
            await db.execute(
                select(Source).where(Source.project_id == project.id, Source.user_id == user_id)
            )
        ).scalars()
    )
    all_quotes = list(
        (
            await db.execute(
                select(Quote).where(Quote.project_id == project.id, Quote.user_id == user_id)
            )
        ).scalars()
    )
    sources = {row.id: row for row in active_revision_rows(all_sources, project.active_revision_id)}
    quotes = {row.id: row for row in active_revision_rows(all_quotes, project.active_revision_id)}

    normalized: list[AIOperation] = []
    for operation in proposal.operations:
        if operation.kind not in spec.allowed_operations:
            raise ProposalValidationError(
                f"Operation {operation.kind!r} is not permitted for task mode {spec.mode!r}."
            )
        payload = dict(operation.payload or {})
        if operation.kind == "replace_runs":
            block_id = str(payload.get("block_id", ""))
            if block_id not in scoped_blocks or block_id not in blocks:
                raise ProposalValidationError("replace_runs target is outside the selected scope.")
            block = blocks[block_id][2]
            if not isinstance(block, (ParagraphBlock, HeadingBlock)):
                raise ProposalValidationError(
                    "AI text replacement is limited to paragraph and heading blocks; quotations remain registry-controlled."
                )
            if isinstance(block, ParagraphBlock):
                runs = payload.get("runs")
                if not isinstance(runs, list) or not runs:
                    raise ProposalValidationError("replace_runs requires a non-empty runs list.")
                for run in runs:
                    if not isinstance(run, dict) or not isinstance(run.get("text"), str):
                        raise ProposalValidationError("Each replacement run requires text.")
                    if set(run) - {"text", "italic"}:
                        raise ProposalValidationError("Replacement runs may contain only text and italic.")
            else:
                if not isinstance(payload.get("text"), str) or not payload["text"].strip():
                    raise ProposalValidationError("Heading replacement requires non-empty text.")
            _reject_unregistered_direct_quote(operation)
        elif operation.kind == "insert_paragraph":
            chapter_id = str(payload.get("chapter_id", ""))
            if chapter_id not in scoped_chapters or chapter_id not in chapters:
                raise ProposalValidationError("Inserted paragraph chapter is outside the selected scope.")
            after_id = payload.get("after_block_id")
            if after_id and str(after_id) not in scoped_blocks:
                raise ProposalValidationError("Inserted paragraph anchor is outside the selected scope.")
            if not payload.get("runs") and not str(payload.get("text", "")).strip():
                raise ProposalValidationError("Inserted paragraph requires text or runs.")
            _reject_unregistered_direct_quote(operation)
        elif operation.kind == "insert_marker":
            block_id = str(payload.get("block_id", ""))
            if block_id not in scoped_blocks or block_id not in blocks:
                raise ProposalValidationError("Marker anchor is outside the selected scope.")
            if payload.get("kind") not in _ALLOWED_MARKERS:
                raise ProposalValidationError("Unsupported editorial marker kind.")
            if not str(payload.get("note", "")).strip():
                raise ProposalValidationError("Editorial marker requires a clear note.")
        elif operation.kind == "move_block":
            block_id = str(payload.get("block_id", ""))
            target_chapter = str(payload.get("to_chapter_id", ""))
            if block_id not in scoped_blocks or block_id not in blocks:
                raise ProposalValidationError("Move source block is outside the selected scope.")
            if target_chapter not in scoped_chapters or target_chapter not in chapters:
                raise ProposalValidationError("Move target chapter is outside the selected scope.")
            operation = operation.model_copy(update={"risk": "high"})
        elif operation.kind == "add_verified_quote":
            quote_id = UUID(str(payload.get("quote_id")))
            chapter_id = str(payload.get("chapter_id", ""))
            if quote_id not in verified_quote_ids or quote_id not in quotes or not quotes[quote_id].verified:
                raise ProposalValidationError(
                    "Direct quotation insertion requires a human-verified quote included in context."
                )
            quote = quotes[quote_id]
            source = sources.get(quote.source_id)
            if source is None or not source.verified or source.id not in verified_source_ids:
                raise ProposalValidationError(
                    "Direct quotation insertion requires its source to be human-verified and included in context."
                )
            if chapter_id not in scoped_chapters or chapter_id not in chapters:
                raise ProposalValidationError("Quotation destination is outside the selected scope.")
            after_id = payload.get("after_block_id")
            if after_id and str(after_id) not in scoped_blocks:
                raise ProposalValidationError("Quotation anchor is outside the selected scope.")
            if set(payload) - {"quote_id", "chapter_id", "after_block_id", "citation"}:
                raise ProposalValidationError(
                    "Quotation operation may reference only quote_id, chapter_id, anchor and citation; text is server-inserted."
                )
            if quote_id not in evidence_quotes:
                raise ProposalValidationError("Inserted quotation must be declared in proposal evidence.")
        normalized.append(operation)

    normalized_payload = proposal.model_copy(update={"operations": normalized})
    return normalized_payload, _maximum_risk(normalized, spec.risk_level)


def _current_hashes(project: Project) -> tuple[dict[str, str], dict[str, str]]:
    document = _document(project)
    block_hashes = {
        str(block.id): _hash(block.model_dump(mode="json"))
        for chapter in document.chapters
        for block in chapter.blocks
    }
    chapter_hashes = {
        str(chapter.id): _hash(chapter.model_dump(mode="json")) for chapter in document.chapters
    }
    return block_hashes, chapter_hashes


def proposal_context_is_current(project: Project, proposal: AIProposal) -> bool:
    if project.document_version == proposal.based_on_document_version:
        return True
    manifest = proposal.context_manifest or {}
    expected_blocks = manifest.get("block_hashes") or {}
    expected_chapters = manifest.get("chapter_hashes") or {}
    if not expected_blocks and not expected_chapters:
        return False
    current_blocks, current_chapters = _current_hashes(project)
    return all(current_blocks.get(key) == value for key, value in expected_blocks.items()) and all(
        current_chapters.get(key) == value for key, value in expected_chapters.items()
    )


async def _translate_operation(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    operation: AIOperation,
) -> dict:
    payload = dict(operation.payload or {})
    if operation.kind == "replace_runs":
        command_payload = {"block_id": str(payload["block_id"])}
        if "runs" in payload:
            command_payload["runs"] = payload["runs"]
        else:
            command_payload["text"] = payload["text"]
        return {"command_type": "update_block_text", "payload": command_payload}
    if operation.kind == "insert_paragraph":
        runs = payload.get("runs") or [{"text": str(payload.get("text", "")), "italic": False}]
        return {
            "command_type": "insert_block",
            "payload": {
                "chapter_id": str(payload["chapter_id"]),
                "after_block_id": str(payload["after_block_id"]) if payload.get("after_block_id") else None,
                "block": {"type": "paragraph", "runs": runs, "origin": "ai_proposal"},
            },
        }
    if operation.kind == "insert_marker":
        return {
            "command_type": "add_marker",
            "payload": {
                "block_id": str(payload["block_id"]),
                "kind": payload["kind"],
                "note": payload["note"],
                "origin": "ai_proposal",
                "evidence": {"origin": "ai_proposal", "reason": operation.reason},
            },
        }
    if operation.kind == "move_block":
        return {
            "command_type": "move_block",
            "payload": {
                "block_id": str(payload["block_id"]),
                "to_chapter_id": str(payload["to_chapter_id"]),
                "to_index": int(payload.get("to_index", 0)),
            },
        }
    if operation.kind == "add_verified_quote":
        quote_id = UUID(str(payload["quote_id"]))
        quote = (
            await db.execute(
                select(Quote).where(
                    Quote.id == quote_id,
                    Quote.project_id == project.id,
                    Quote.user_id == user_id,
                    Quote.verified.is_(True),
                )
            )
        ).scalar_one_or_none()
        if quote is None:
            raise ProposalValidationError("The verified quotation is no longer available.")
        source = (
            await db.execute(
                select(Source).where(
                    Source.id == quote.source_id,
                    Source.project_id == project.id,
                    Source.user_id == user_id,
                    Source.verified.is_(True),
                )
            )
        ).scalar_one_or_none()
        if source is None:
            raise ProposalValidationError("The quotation source is no longer verified.")
        citation = str(payload.get("citation") or quote.page_or_loc or "").strip()
        return {
            "command_type": "insert_block",
            "payload": {
                "chapter_id": str(payload["chapter_id"]),
                "after_block_id": str(payload["after_block_id"]) if payload.get("after_block_id") else None,
                "block": {
                    "type": "block_quote",
                    "text": quote.text,
                    "citation": citation,
                    "quote_id": str(quote.id),
                    "origin": "ai_proposal",
                },
            },
        }
    raise ProposalValidationError(f"Unsupported proposal operation: {operation.kind}")


async def decide_proposal(
    db: AsyncSession,
    project: Project,
    proposal: AIProposal,
    user_id: UUID,
    decision: ProposalDecision,
) -> tuple[AIProposal, DocumentCommand | None]:
    if proposal.status not in {"open", "stale"}:
        raise ProposalValidationError("This proposal already has a final decision.")
    if project.document_version != decision.expected_document_version:
        raise VersionConflict(decision.expected_document_version, project.document_version)

    now = datetime.now(timezone.utc)
    if decision.action in {"reject", "supersede"}:
        proposal.status = "rejected" if decision.action == "reject" else "superseded"
        proposal.selected_operation_indexes = []
        proposal.decision_note = decision.decision_note
        proposal.rejection_reason = decision.rejection_reason
        proposal.decision_by = user_id
        proposal.decided_at = now
        db.add(
            Event(
                project_id=project.id,
                user_id=user_id,
                kind="ai_proposal_rejected" if decision.action == "reject" else "ai_proposal_superseded",
                data={
                    "proposal_id": str(proposal.id),
                    "reason": decision.rejection_reason,
                    "prompt_version": proposal.prompt_version,
                    "model": proposal.model,
                },
            )
        )
        await db.commit()
        await db.refresh(proposal)
        return proposal, None

    if not proposal_context_is_current(project, proposal):
        proposal.status = "stale"
        await db.commit()
        raise ProposalStaleError(
            "The canonical content examined by this proposal changed. Regenerate it against the current version."
        )

    original_operations = [AIOperation.model_validate(item) for item in proposal.operations]
    if decision.action == "accept_all":
        selected = list(range(len(original_operations)))
    else:
        selected = sorted(set(decision.selected_operation_indexes))
    if not selected or any(index < 0 or index >= len(original_operations) for index in selected):
        raise ProposalValidationError("Selected operation indexes are invalid.")

    chosen: list[AIOperation] = []
    edited: dict[str, dict] = {}
    for index in selected:
        operation = decision.operation_overrides.get(index, original_operations[index])
        chosen.append(operation)
        if index in decision.operation_overrides:
            edited[str(index)] = operation.model_dump(mode="json")

    max_risk = _maximum_risk(chosen, proposal.risk_level)
    if max_risk == "high" and not (decision.decision_note or "").strip():
        raise ProposalValidationError("High-risk structural changes require a human decision note.")

    spec = TaskSpec(
        mode=proposal.task_mode,
        prompt_name=proposal.prompt_name,
        prompt_version=proposal.prompt_version,
        result_type="proposal",
        risk_level=proposal.risk_level,
        model_tier="reasoning",
        allowed_operations=tuple({operation.kind for operation in original_operations}),
        maximum_scope="selection",
        description="Stored proposal revalidation",
    )
    revalidated, _ = await validate_proposal_payload(
        db,
        project,
        user_id,
        spec,
        AIProposalPayload(
            rationale=proposal.rationale,
            explanation=proposal.explanation,
            operations=chosen,
            evidence=proposal.evidence,
            assumptions=proposal.assumptions,
            unresolved_requirements=proposal.unresolved_requirements,
        ),
        proposal.context_manifest,
    )
    commands = [
        await _translate_operation(db, project, user_id, operation)
        for operation in revalidated.operations
    ]
    before = await verify_project(db, project)
    command_type = commands[0]["command_type"] if len(commands) == 1 else "batch"
    command_payload = commands[0]["payload"] if len(commands) == 1 else {"commands": commands}
    command, _ = await apply_project_command(
        db,
        project,
        user_id,
        command_type=command_type,
        payload=command_payload,
        expected_version=project.document_version,
        client_request_id=f"ai-proposal-{proposal.id}-{'-'.join(map(str, selected))}",
        summary=f"Accept {len(selected)} Robofox Scholar proposal operation(s)",
    )

    # apply_project_command commits and refreshes the project. Re-run deterministic
    # verification and invalidate navigation memories derived from older content.
    _, after, _ = await sync_review_items(db, project)
    await db.execute(
        update(AIMemory)
        .where(
            AIMemory.project_id == project.id,
            AIMemory.based_on_document_version != project.document_version,
        )
        .values(stale=True)
    )
    proposal.status = "accepted" if len(selected) == len(original_operations) else "partially_accepted"
    proposal.selected_operation_indexes = selected
    proposal.human_edited_operations = edited
    proposal.decision_note = decision.decision_note
    proposal.rejection_reason = None
    proposal.decision_by = user_id
    proposal.decided_at = now
    proposal.applied_command_id = command.id
    proposal.verifier_before = before
    proposal.verifier_after = after
    db.add(
        Event(
            project_id=project.id,
            user_id=user_id,
            kind="ai_proposal_applied",
            data={
                "proposal_id": str(proposal.id),
                "selected_operation_indexes": selected,
                "human_edited_indexes": sorted(int(value) for value in edited),
                "document_version": project.document_version,
                "command_id": str(command.id),
                "model": proposal.model,
                "prompt_name": proposal.prompt_name,
                "prompt_version": proposal.prompt_version,
                "context_hash": proposal.context_hash,
            },
        )
    )
    await db.commit()
    await db.refresh(proposal)
    return proposal, command
