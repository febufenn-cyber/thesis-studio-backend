"""Snapshot-bound review cycles, anchored comments and human suggestions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.canonical.migrations import project_payload
from app.canonical.model import ThesisDocument
from app.collaboration.approval_invalidation import invalidate_approvals_for_command
from app.collaboration.notifications import notify, notify_project_roles
from app.models.document_snapshot import DocumentSnapshot
from app.models.event import Event
from app.models.project import Project
from app.models.review_collaboration import (
    ApprovalRecord,
    CollaborationComment,
    HumanSuggestion,
    ReviewCycle,
    SupervisorInstruction,
)
from app.models.tenancy import ReviewAssignment
from app.services.editor_service import apply_project_command, create_snapshot


class WorkflowError(RuntimeError):
    pass


WORKFLOW_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"imported", "student_review", "supervisor_review"},
    "imported": {"student_review", "supervisor_review"},
    "student_review": {"supervisor_review"},
    "supervisor_review": {"changes_requested", "academically_approved"},
    "changes_requested": {"student_review", "supervisor_review"},
    "academically_approved": {"formatting_review", "post_viva_corrections"},
    "formatting_review": {"academically_approved", "submission_ready"},
    "submission_ready": {"submitted", "formatting_review"},
    "submitted": {"post_viva_corrections", "final_archived"},
    "post_viva_corrections": {"supervisor_review", "submission_ready", "final_archived"},
    "final_archived": set(),
}

TRANSITION_CAPABILITIES: dict[tuple[str, str], str] = {
    ("draft", "supervisor_review"): "project.submit_review",
    ("imported", "supervisor_review"): "project.submit_review",
    ("student_review", "supervisor_review"): "project.submit_review",
    ("changes_requested", "supervisor_review"): "project.submit_review",
    ("supervisor_review", "changes_requested"): "project.approve_chapter",
    ("supervisor_review", "academically_approved"): "project.approve_academic",
    ("academically_approved", "formatting_review"): "project.prepare_export",
    ("formatting_review", "submission_ready"): "project.approve_formatting",
    ("submission_ready", "submitted"): "project.transition_submission",
    ("submitted", "post_viva_corrections"): "project.transition_submission",
    ("submitted", "final_archived"): "project.transition_submission",
}


def canonical_checksum(project: Project) -> str:
    raw = json.dumps(
        project_payload(project), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _document(project: Project) -> ThesisDocument:
    return ThesisDocument.model_validate(project_payload(project))


def find_block(project: Project, block_id: UUID) -> tuple[UUID | None, dict] | None:
    document = _document(project)
    for chapter in document.chapters:
        for block in chapter.blocks:
            if block.id == block_id:
                return chapter.id, block.model_dump(mode="json")
    for entry in document.front_matter:
        for block in entry.body_blocks:
            if block.id == block_id:
                return entry.id, block.model_dump(mode="json")
    return None


def block_text(block: dict) -> str:
    kind = block.get("type")
    if kind == "paragraph":
        return "".join(str(run.get("text", "")) for run in block.get("runs", []))
    if kind in {"heading", "block_quote"}:
        return str(block.get("text", ""))
    if kind == "verse_quote":
        return "\n".join(str(line) for line in block.get("lines", []))
    return str(block.get("note", ""))


def require_transition(project: Project, target: str, capabilities: set[str] | frozenset[str]) -> None:
    current = project.workflow_state
    if target not in WORKFLOW_TRANSITIONS.get(current, set()):
        raise WorkflowError(f"Invalid thesis workflow transition: {current} → {target}")
    required = TRANSITION_CAPABILITIES.get((current, target))
    if required and required not in capabilities:
        raise WorkflowError("The current role cannot perform this workflow transition.")


async def transition_project(
    db: AsyncSession,
    project: Project,
    actor_id: UUID,
    target: str,
    capabilities: set[str] | frozenset[str],
    *,
    note: str | None = None,
) -> None:
    require_transition(project, target, capabilities)
    previous = project.workflow_state
    project.workflow_state = target
    db.add(
        Event(
            project_id=project.id,
            user_id=actor_id,
            kind="workflow_state_changed",
            data={"from": previous, "to": target, "note": note},
        )
    )
    await db.flush()


async def submit_for_review(
    db: AsyncSession,
    project: Project,
    submitter_id: UUID,
    reviewer_id: UUID,
    capabilities: set[str] | frozenset[str],
    *,
    scope_type: str,
    scope_id: UUID | None,
    deadline: datetime | None,
    resubmitted_from_id: UUID | None = None,
) -> ReviewCycle:
    if "project.submit_review" not in capabilities:
        raise WorkflowError("Only the student author or an authorised editor may submit review.")
    if scope_type not in {"project", "chapter", "front_matter"}:
        raise WorkflowError("Unsupported review scope.")
    if scope_type != "project" and scope_id is None:
        raise WorkflowError("A scoped review requires a stable scope id.")

    count = int(
        (
            await db.execute(
                select(func.count(ReviewCycle.id)).where(ReviewCycle.project_id == project.id)
            )
        ).scalar_one()
    )
    snapshot = await create_snapshot(
        db,
        project,
        submitter_id,
        name=f"Review cycle {count + 1} — {scope_type}",
        reason="review_submission",
        automatic=False,
    )
    cycle = ReviewCycle(
        project_id=project.id,
        snapshot_id=snapshot.id,
        cycle_number=count + 1,
        scope_type=scope_type,
        scope_id=scope_id,
        submitted_document_version=project.document_version,
        submitted_checksum=snapshot.checksum,
        submitted_by=submitter_id,
        reviewer_id=reviewer_id,
        status="submitted",
        deadline=deadline,
        resubmitted_from_id=resubmitted_from_id,
    )
    db.add(cycle)
    await db.flush()
    assignment = ReviewAssignment(
        project_id=project.id,
        assignee_id=reviewer_id,
        assigned_by=submitter_id,
        assignment_type="supervisor_review",
        scope={"review_cycle_id": str(cycle.id), "scope_type": scope_type, "scope_id": str(scope_id) if scope_id else None},
        due_at=deadline,
        priority="normal",
    )
    db.add(assignment)
    if project.workflow_state in {"draft", "imported", "student_review", "changes_requested"}:
        previous = project.workflow_state
        project.workflow_state = "supervisor_review"
    else:
        previous = project.workflow_state
    db.add(
        Event(
            project_id=project.id,
            user_id=submitter_id,
            kind="review_cycle_submitted",
            data={
                "review_cycle_id": str(cycle.id),
                "cycle_number": cycle.cycle_number,
                "snapshot_id": str(snapshot.id),
                "scope_type": scope_type,
                "scope_id": str(scope_id) if scope_id else None,
                "document_version": project.document_version,
                "checksum": snapshot.checksum,
                "workflow_from": previous,
                "workflow_to": project.workflow_state,
            },
        )
    )
    await notify(
        db,
        reviewer_id,
        kind="review_submitted",
        title="Thesis review assigned",
        body=f"Review cycle {cycle.cycle_number} is ready. Open the workspace to review the submitted snapshot.",
        project_id=project.id,
        data={"review_cycle_id": str(cycle.id)},
    )
    await db.commit()
    await db.refresh(cycle)
    return cycle


async def decide_review(
    db: AsyncSession,
    project: Project,
    cycle: ReviewCycle,
    reviewer_id: UUID,
    capabilities: set[str] | frozenset[str],
    *,
    decision: str,
    note: str,
) -> ApprovalRecord | None:
    if cycle.reviewer_id != reviewer_id:
        raise WorkflowError("This review cycle is assigned to another reviewer.")
    if cycle.status not in {"submitted", "in_review"}:
        raise WorkflowError("This review cycle is no longer open.")
    allowed = {"approved", "approved_with_minor_changes", "changes_requested", "not_ready", "withdrawn"}
    if decision not in allowed:
        raise WorkflowError("Unsupported review decision.")
    if decision in {"approved", "approved_with_minor_changes"} and "project.approve_chapter" not in capabilities and "project.approve_academic" not in capabilities:
        raise WorkflowError("The current role cannot approve academic content.")

    cycle.status = "decided"
    cycle.decision = decision
    cycle.decision_note = note
    cycle.decided_at = datetime.now(timezone.utc)
    cycle.current_document_version_at_decision = project.document_version
    approval: ApprovalRecord | None = None
    if decision in {"approved", "approved_with_minor_changes"}:
        current_matches = (
            project.document_version == cycle.submitted_document_version
            and canonical_checksum(project) == cycle.submitted_checksum
        )
        approval = ApprovalRecord(
            project_id=project.id,
            review_cycle_id=cycle.id,
            snapshot_id=cycle.snapshot_id,
            dimension="content",
            scope_type=cycle.scope_type,
            scope_id=cycle.scope_id,
            decision=decision,
            status="active" if current_matches else "snapshot_only",
            approved_by=reviewer_id,
            document_version=cycle.submitted_document_version,
            document_checksum=cycle.submitted_checksum,
            note=note,
        )
        db.add(approval)
        if current_matches and cycle.scope_type == "project":
            project.workflow_state = "academically_approved"
    elif decision in {"changes_requested", "not_ready"}:
        project.workflow_state = "changes_requested"

    assignments = list(
        (
            await db.execute(
                select(ReviewAssignment).where(
                    ReviewAssignment.project_id == project.id,
                    ReviewAssignment.assignee_id == reviewer_id,
                    ReviewAssignment.status == "open",
                )
            )
        ).scalars()
    )
    for assignment in assignments:
        if (assignment.scope or {}).get("review_cycle_id") == str(cycle.id):
            assignment.status = "completed"
            assignment.completed_at = datetime.now(timezone.utc)

    db.add(
        Event(
            project_id=project.id,
            user_id=reviewer_id,
            kind="review_cycle_decided",
            data={
                "review_cycle_id": str(cycle.id),
                "decision": decision,
                "approval_id": str(approval.id) if approval else None,
                "reviewed_document_version": cycle.submitted_document_version,
                "current_document_version": project.document_version,
                "applies_to_current_document": bool(approval and approval.status == "active"),
            },
        )
    )
    await notify(
        db,
        cycle.submitted_by,
        kind="review_decided",
        title="Supervisor review updated",
        body=f"Review cycle {cycle.cycle_number} received the decision: {decision.replace('_', ' ')}.",
        project_id=project.id,
        data={"review_cycle_id": str(cycle.id), "decision": decision},
    )
    await db.commit()
    if approval:
        await db.refresh(approval)
    return approval


async def create_comment(
    db: AsyncSession,
    project: Project,
    author_id: UUID,
    *,
    anchor_type: str,
    anchor: dict,
    body: str,
    review_cycle_id: UUID | None = None,
    parent_id: UUID | None = None,
    assigned_to: UUID | None = None,
    visibility: str = "project_members",
) -> CollaborationComment:
    selected = anchor.get("selected_text_snapshot")
    state = "current"
    if anchor_type == "block_range":
        block_id = UUID(str(anchor.get("block_id")))
        found = find_block(project, block_id)
        if found is None:
            raise WorkflowError("Comment target block does not exist.")
        text = block_text(found[1])
        start = int(anchor.get("start_offset", 0))
        end = int(anchor.get("end_offset", start))
        if start < 0 or end < start or end > len(text):
            raise WorkflowError("Comment text range is outside the target block.")
        selected = selected if selected is not None else text[start:end]
    comment = CollaborationComment(
        project_id=project.id,
        review_cycle_id=review_cycle_id,
        author_id=author_id,
        parent_id=parent_id,
        anchor_type=anchor_type,
        anchor={key: value for key, value in anchor.items() if key != "selected_text_snapshot"},
        selected_text_snapshot=selected,
        document_version=project.document_version,
        anchor_state=state,
        body=body,
        visibility=visibility,
        assigned_to=assigned_to,
    )
    db.add(comment)
    await db.flush()
    db.add(
        Event(
            project_id=project.id,
            user_id=author_id,
            kind="collaboration_comment_added",
            data={"comment_id": str(comment.id), "anchor_type": anchor_type, "review_cycle_id": str(review_cycle_id) if review_cycle_id else None},
        )
    )
    if assigned_to:
        await notify(
            db,
            assigned_to,
            kind="comment_assigned",
            title="A thesis comment needs your response",
            body="A collaborator assigned a comment to you. Open the project to view it.",
            project_id=project.id,
            data={"comment_id": str(comment.id)},
        )
    await db.commit()
    await db.refresh(comment)
    return comment


def refresh_comment_anchor(project: Project, comment: CollaborationComment) -> str:
    if comment.anchor_type != "block_range":
        return "current"
    block_id = comment.anchor.get("block_id")
    found = find_block(project, UUID(str(block_id))) if block_id else None
    if found is None:
        return "orphaned"
    text = block_text(found[1])
    selected = comment.selected_text_snapshot or ""
    start = int(comment.anchor.get("start_offset", 0))
    end = int(comment.anchor.get("end_offset", start))
    if selected and 0 <= start <= end <= len(text) and text[start:end] == selected:
        return "current"
    if selected:
        locations: list[int] = []
        offset = 0
        while True:
            index = text.find(selected, offset)
            if index < 0:
                break
            locations.append(index)
            offset = index + 1
        if len(locations) == 1:
            comment.anchor = {**comment.anchor, "start_offset": locations[0], "end_offset": locations[0] + len(selected)}
            return "moved_successfully"
        if len(locations) > 1:
            return "possibly_outdated"
    return "orphaned"


async def create_suggestion(
    db: AsyncSession,
    project: Project,
    author_id: UUID,
    *,
    target_block_id: UUID,
    proposed_operation: dict,
    explanation: str,
    review_cycle_id: UUID | None = None,
) -> HumanSuggestion:
    found = find_block(project, target_block_id)
    if found is None:
        raise WorkflowError("Suggestion target block does not exist.")
    command_type = proposed_operation.get("command_type")
    if command_type not in {"update_block_text", "insert_block", "add_marker", "move_block"}:
        raise WorkflowError("Suggestions must use a bounded Phase 2 command.")
    payload = proposed_operation.get("payload") or {}
    target = payload.get("block_id") or payload.get("after_block_id")
    if target and str(target) != str(target_block_id):
        raise WorkflowError("Suggestion operation is not anchored to the selected block.")
    row = HumanSuggestion(
        project_id=project.id,
        review_cycle_id=review_cycle_id,
        author_id=author_id,
        target_block_id=target_block_id,
        based_on_document_version=project.document_version,
        before_block=found[1],
        proposed_operation=proposed_operation,
        explanation=explanation,
    )
    db.add(row)
    await db.flush()
    db.add(
        Event(
            project_id=project.id,
            user_id=author_id,
            kind="human_suggestion_opened",
            data={"suggestion_id": str(row.id), "target_block_id": str(target_block_id)},
        )
    )
    await notify_project_roles(
        db,
        project.id,
        {"student"},
        kind="suggestion_added",
        title="A collaborator proposed a thesis change",
        body="A structured suggestion is ready for the student author's review.",
        exclude_user_id=author_id,
        data={"suggestion_id": str(row.id)},
    )
    await db.commit()
    await db.refresh(row)
    return row


async def decide_suggestion(
    db: AsyncSession,
    project: Project,
    suggestion: HumanSuggestion,
    actor_id: UUID,
    capabilities: set[str] | frozenset[str],
    *,
    decision: str,
    response: str | None = None,
    operation_override: dict | None = None,
) -> HumanSuggestion:
    if "project.accept_suggestion" not in capabilities and "project.edit_content" not in capabilities:
        raise WorkflowError("Only the student author or an authorised editor may decide suggestions.")
    if suggestion.status != "open":
        raise WorkflowError("This suggestion has already been decided.")
    if decision not in {"accepted", "rejected", "resolved_manually"}:
        raise WorkflowError("Unsupported suggestion decision.")

    current = find_block(project, suggestion.target_block_id)
    if current is None:
        suggestion.status = "outdated"
        await db.commit()
        raise WorkflowError("The suggestion target no longer exists.")
    if current[1] != suggestion.before_block and decision == "accepted":
        suggestion.status = "outdated"
        await db.commit()
        raise WorkflowError("The target block changed after this suggestion was created.")

    suggestion.student_response = response
    suggestion.decision_by = actor_id
    suggestion.decision_at = datetime.now(timezone.utc)
    if decision == "accepted":
        operation = operation_override or suggestion.proposed_operation
        command, result = await apply_project_command(
            db,
            project,
            actor_id,
            command_type=operation["command_type"],
            payload=operation.get("payload", {}),
            expected_version=project.document_version,
            client_request_id=f"human-suggestion-{suggestion.id}",
            summary=f"Accept collaborator suggestion: {suggestion.explanation[:200]}",
        )
        suggestion.applied_command_id = command.id
        suggestion.status = "accepted"
        await invalidate_approvals_for_command(db, project, actor_id, operation["command_type"], result)
    elif decision == "rejected":
        suggestion.status = "rejected"
    else:
        suggestion.status = "resolved_manually"
        suggestion.manual_resolution_note = response

    db.add(
        Event(
            project_id=project.id,
            user_id=actor_id,
            kind="human_suggestion_decided",
            data={
                "suggestion_id": str(suggestion.id),
                "decision": suggestion.status,
                "applied_command_id": str(suggestion.applied_command_id) if suggestion.applied_command_id else None,
            },
        )
    )
    await notify(
        db,
        suggestion.author_id,
        kind="suggestion_decided",
        title="Your thesis suggestion was reviewed",
        body=f"The student author marked the suggestion as {suggestion.status.replace('_', ' ')}.",
        project_id=project.id,
        data={"suggestion_id": str(suggestion.id)},
    )
    await db.commit()
    await db.refresh(suggestion)
    return suggestion


async def add_supervisor_instruction(
    db: AsyncSession,
    project: Project,
    author_id: UUID,
    *,
    scope_type: str,
    scope_id: UUID | None,
    instruction_type: str,
    priority: str,
    text: str,
    structured: dict | None = None,
    due_at: datetime | None = None,
) -> SupervisorInstruction:
    row = SupervisorInstruction(
        project_id=project.id,
        author_id=author_id,
        scope_type=scope_type,
        scope_id=scope_id,
        instruction_type=instruction_type,
        priority=priority,
        text=text,
        structured=structured or {},
        due_at=due_at,
    )
    db.add(row)
    await db.flush()
    policy = dict(project.ai_policy or {})
    constraints = list(policy.get("supervisor_constraints") or [])
    constraints.append(
        {
            "instruction_id": str(row.id),
            "scope_type": scope_type,
            "scope_id": str(scope_id) if scope_id else None,
            "priority": priority,
            "text": text,
            "status": "active",
        }
    )
    policy["supervisor_constraints"] = constraints[-100:]
    project.ai_policy = policy
    db.add(
        Event(
            project_id=project.id,
            user_id=author_id,
            kind="supervisor_instruction_added",
            data={"instruction_id": str(row.id), "priority": priority, "scope_type": scope_type},
        )
    )
    await db.commit()
    await db.refresh(row)
    return row
