"""Phase 4 collaboration API: memberships, review, comments, suggestions and queues."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collaboration.audit import project_timeline
from app.collaboration.capabilities import (
    ROLE_CAPABILITIES,
    accessible_project_ids,
    require_institution_capability,
    require_project_capability,
    resolve_project_access,
)
from app.collaboration.notifications import notify
from app.collaboration.workflow import (
    WorkflowError,
    add_supervisor_instruction,
    canonical_checksum,
    create_comment,
    create_suggestion,
    decide_review,
    decide_suggestion,
    refresh_comment_anchor,
    submit_for_review,
    transition_project,
)
from app.api.deps import CurrentUser
from app.db.deps import get_db
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
from app.models.tenancy import (
    Department,
    MembershipInvitation,
    Notification,
    NotificationPreference,
    OrganizationMembership,
    ProjectHandoff,
    ProjectMembership,
    ReviewAssignment,
)
from app.models.user import User
from app.services.editor_service import create_snapshot


router = APIRouter(tags=["collaboration"])


class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=240)
    code: str | None = Field(None, max_length=60)
    description: str | None = Field(None, max_length=4000)


class InvitationCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: Literal["student", "supervisor", "operator", "department_admin", "institution_admin"]
    department_id: UUID | None = None
    project_id: UUID | None = None
    capabilities: list[str] = Field(default_factory=list, max_length=60)
    expires_in_days: int = Field(7, ge=1, le=30)


class InvitationAccept(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)


class MembershipPatch(BaseModel):
    status: Literal["active", "revoked", "suspended"] | None = None
    capabilities: list[str] | None = None
    content_access: bool | None = None
    source_access: bool | None = None
    ai_history_access: bool | None = None
    expires_at: datetime | None = None


class ReviewSubmit(BaseModel):
    reviewer_id: UUID
    scope_type: Literal["project", "chapter", "front_matter"] = "project"
    scope_id: UUID | None = None
    deadline: datetime | None = None
    resubmitted_from_id: UUID | None = None


class ReviewDecision(BaseModel):
    decision: Literal["approved", "approved_with_minor_changes", "changes_requested", "not_ready", "withdrawn"]
    note: str = Field(..., min_length=2, max_length=8000)


class CommentCreate(BaseModel):
    anchor_type: Literal["project", "chapter", "block", "block_range", "source", "quote", "review_issue", "metadata", "preview_page"]
    anchor: dict[str, Any] = Field(default_factory=dict)
    body: str = Field(..., min_length=1, max_length=12000)
    review_cycle_id: UUID | None = None
    parent_id: UUID | None = None
    assigned_to: UUID | None = None
    visibility: Literal["project_members", "student_supervisor", "private_author"] = "project_members"


class CommentPatch(BaseModel):
    action: Literal["resolve", "reopen", "reanchor"]
    anchor: dict[str, Any] | None = None


class SuggestionCreate(BaseModel):
    target_block_id: UUID
    proposed_operation: dict[str, Any]
    explanation: str = Field(..., min_length=2, max_length=8000)
    review_cycle_id: UUID | None = None


class SuggestionDecision(BaseModel):
    decision: Literal["accepted", "rejected", "resolved_manually"]
    response: str | None = Field(None, max_length=8000)
    operation_override: dict[str, Any] | None = None


class ApprovalCreate(BaseModel):
    dimension: Literal["content", "citation", "formatting", "institutional", "submission"]
    scope_type: Literal["project", "chapter", "front_matter"] = "project"
    scope_id: UUID | None = None
    decision: Literal["approved", "approved_with_minor_changes"] = "approved"
    note: str | None = Field(None, max_length=8000)
    review_cycle_id: UUID | None = None


class InstructionCreate(BaseModel):
    scope_type: Literal["project", "chapter", "block"] = "project"
    scope_id: UUID | None = None
    instruction_type: str = Field(..., min_length=2, max_length=50)
    priority: Literal["mandatory", "recommendation"] = "mandatory"
    text: str = Field(..., min_length=2, max_length=12000)
    structured: dict[str, Any] = Field(default_factory=dict)
    due_at: datetime | None = None


class AssignmentCreate(BaseModel):
    assignee_id: UUID
    assignment_type: Literal["supervisor_review", "formatting_review", "ingestion_review", "citation_review", "submission_review"]
    scope: dict[str, Any] = Field(default_factory=dict)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    due_at: datetime | None = None


class HandoffCreate(BaseModel):
    previous_user_id: UUID | None = None
    new_user_id: UUID
    role: Literal["supervisor", "operator", "department_admin"]
    reason: str = Field(..., min_length=2, max_length=8000)
    outstanding_items: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    effective_at: datetime | None = None


class TransitionRequest(BaseModel):
    target: str
    note: str | None = Field(None, max_length=4000)


class NotificationPreferencePatch(BaseModel):
    kind: str = Field(..., min_length=2, max_length=60)
    cadence: Literal["immediate", "daily", "weekly", "muted"]
    email_enabled: bool = True
    content_preview: bool = False


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _membership_dict(row: ProjectMembership) -> dict:
    return {
        "id": row.id, "project_id": row.project_id, "user_id": row.user_id,
        "role": row.role, "status": row.status, "capabilities": row.capabilities,
        "content_access": row.content_access, "source_access": row.source_access,
        "ai_history_access": row.ai_history_access, "expires_at": row.expires_at,
        "revoked_at": row.revoked_at, "created_at": row.created_at,
    }


def _cycle_dict(row: ReviewCycle) -> dict:
    return {
        "id": row.id, "project_id": row.project_id, "snapshot_id": row.snapshot_id,
        "cycle_number": row.cycle_number, "scope_type": row.scope_type, "scope_id": row.scope_id,
        "submitted_document_version": row.submitted_document_version,
        "submitted_checksum": row.submitted_checksum, "submitted_by": row.submitted_by,
        "reviewer_id": row.reviewer_id, "status": row.status, "decision": row.decision,
        "decision_note": row.decision_note, "deadline": row.deadline,
        "submitted_at": row.submitted_at, "decided_at": row.decided_at,
        "current_document_version_at_decision": row.current_document_version_at_decision,
        "resubmitted_from_id": row.resubmitted_from_id,
    }


def _comment_dict(row: CollaborationComment) -> dict:
    return {
        "id": row.id, "review_cycle_id": row.review_cycle_id, "author_id": row.author_id,
        "parent_id": row.parent_id, "anchor_type": row.anchor_type, "anchor": row.anchor,
        "selected_text_snapshot": row.selected_text_snapshot, "document_version": row.document_version,
        "anchor_state": row.anchor_state, "body": row.body, "visibility": row.visibility,
        "status": row.status, "assigned_to": row.assigned_to, "resolved_by": row.resolved_by,
        "resolved_at": row.resolved_at, "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _suggestion_dict(row: HumanSuggestion) -> dict:
    return {
        "id": row.id, "review_cycle_id": row.review_cycle_id, "author_id": row.author_id,
        "target_block_id": row.target_block_id, "based_on_document_version": row.based_on_document_version,
        "before_block": row.before_block, "proposed_operation": row.proposed_operation,
        "explanation": row.explanation, "status": row.status, "student_response": row.student_response,
        "decision_by": row.decision_by, "decision_at": row.decision_at,
        "applied_command_id": row.applied_command_id, "created_at": row.created_at,
    }


def _approval_dict(row: ApprovalRecord) -> dict:
    return {
        "id": row.id, "review_cycle_id": row.review_cycle_id, "snapshot_id": row.snapshot_id,
        "dimension": row.dimension, "scope_type": row.scope_type, "scope_id": row.scope_id,
        "decision": row.decision, "status": row.status, "approved_by": row.approved_by,
        "document_version": row.document_version, "document_checksum": row.document_checksum,
        "note": row.note, "invalidated_reason": row.invalidated_reason,
        "approved_at": row.approved_at, "invalidated_at": row.invalidated_at,
    }


@router.get("/collaboration/projects")
async def list_collaboration_projects(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    ids = await accessible_project_ids(db, current_user, "project.read_metadata")
    rows = list((await db.execute(select(Project).where(Project.id.in_(ids)).order_by(Project.updated_at.desc()))).scalars()) if ids else []
    result = []
    for project in rows:
        access = await resolve_project_access(db, project.id, current_user)
        if not access:
            continue
        result.append({
            "id": project.id, "title": project.title, "workflow_state": project.workflow_state,
            "document_version": project.document_version, "institution_id": project.institution_id,
            "department_id": project.department_id, "role": access.role,
            "capabilities": sorted(access.capabilities), "content_access": access.content_access,
            "source_access": access.source_access, "ai_history_access": access.ai_history_access,
            "updated_at": project.updated_at,
        })
    return result


@router.get("/projects/{project_id}/collaboration/access")
async def collaboration_access(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.read_metadata")
    return {
        "project_id": project_id, "role": access.role,
        "capabilities": sorted(access.capabilities), "content_access": access.content_access,
        "source_access": access.source_access, "ai_history_access": access.ai_history_access,
        "workflow_state": access.project.workflow_state,
    }


@router.post("/institutions/{institution_id}/departments", status_code=201)
async def create_department(
    institution_id: UUID,
    body: DepartmentCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "membership.manage_institution")
    row = Department(
        institution_id=institution_id,
        name=body.name.strip(),
        code=body.code,
        description=body.description,
        created_by=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "name": row.name, "code": row.code, "active": row.active}


@router.get("/institutions/{institution_id}/departments")
async def list_departments(
    institution_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    membership = await require_institution_capability(db, institution_id, current_user, "project.read_metadata")
    query = select(Department).where(Department.institution_id == institution_id, Department.active.is_(True))
    if membership.role == "department_admin" and membership.department_id:
        query = query.where(Department.id == membership.department_id)
    rows = list((await db.execute(query.order_by(Department.name))).scalars())
    return [{"id": row.id, "name": row.name, "code": row.code, "description": row.description} for row in rows]


@router.post("/institutions/{institution_id}/invitations", status_code=201)
async def create_invitation(
    institution_id: UUID,
    body: InvitationCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project_access = None
    if body.project_id:
        project_access = await require_project_capability(db, body.project_id, current_user, "membership.invite_reviewer")
        if project_access.project.institution_id != institution_id:
            raise HTTPException(status_code=404, detail="Institution workspace not found")
        if project_access.role == "student" and body.role not in {"supervisor", "operator"}:
            raise HTTPException(status_code=404, detail="Institution workspace not found")
    else:
        capability = "membership.manage_institution" if body.role == "institution_admin" else "membership.manage_department"
        await require_institution_capability(db, institution_id, current_user, capability, department_id=body.department_id)
    token = secrets.token_urlsafe(32)
    row = MembershipInvitation(
        institution_id=institution_id,
        department_id=body.department_id,
        project_id=body.project_id,
        email=body.email.strip().lower(),
        role=body.role,
        capabilities=body.capabilities,
        token_hash=_hash_token(token),
        invited_by=current_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=body.expires_in_days),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {
        "id": row.id, "email": row.email, "role": row.role, "status": row.status,
        "expires_at": row.expires_at, "invitation_token": token,
        "privacy_notice": "Send this token only to the intended recipient. It is returned once and is not stored in plaintext.",
    }


@router.post("/collaboration/invitations/accept")
async def accept_invitation(
    body: InvitationAccept,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(MembershipInvitation).where(
                MembershipInvitation.token_hash == _hash_token(body.token),
                MembershipInvitation.status == "pending",
                MembershipInvitation.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if row is None or row.email != current_user.email.lower():
        raise HTTPException(status_code=404, detail="Invitation not found")
    org = (
        await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.institution_id == row.institution_id,
                OrganizationMembership.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if org is None:
        org = OrganizationMembership(
            institution_id=row.institution_id,
            department_id=row.department_id,
            user_id=current_user.id,
            role=row.role if row.role in {"department_admin", "institution_admin"} else row.role,
            affiliation_status="admin_verified",
            status="active",
            invited_by=row.invited_by,
            verified_by=row.invited_by,
            verified_at=now,
        )
        db.add(org)
    else:
        org.status = "active"
        org.affiliation_status = "admin_verified"
        if row.department_id:
            org.department_id = row.department_id
    project_membership = None
    if row.project_id:
        project_membership = (
            await db.execute(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == row.project_id,
                    ProjectMembership.user_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if project_membership is None:
            project_membership = ProjectMembership(
                project_id=row.project_id,
                user_id=current_user.id,
                role=row.role,
                status="active",
                capabilities=row.capabilities,
                content_access=row.role in {"supervisor", "operator", "student"},
                source_access=row.role in {"supervisor", "operator", "student"},
                ai_history_access=False,
                granted_by=row.invited_by,
            )
            db.add(project_membership)
        else:
            project_membership.status = "active"
            project_membership.revoked_at = None
    row.status = "accepted"
    row.accepted_by = current_user.id
    row.accepted_at = now
    db.add(
        Event(
            project_id=row.project_id,
            user_id=current_user.id,
            kind="project_membership_granted" if row.project_id else "organization_membership_granted",
            data={"invitation_id": str(row.id), "role": row.role, "institution_id": str(row.institution_id)},
        )
    )
    await db.commit()
    return {"accepted": True, "institution_id": row.institution_id, "project_id": row.project_id, "role": row.role}


@router.get("/projects/{project_id}/members")
async def list_project_members(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    access = await require_project_capability(db, project_id, current_user, "project.read_metadata")
    if access.role not in {"student", "department_admin", "institution_admin"} and "assignment.manage" not in access.capabilities:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = list((await db.execute(select(ProjectMembership).where(ProjectMembership.project_id == project_id))).scalars())
    return [_membership_dict(row) for row in rows]


@router.patch("/projects/{project_id}/members/{membership_id}")
async def patch_project_membership(
    project_id: UUID,
    membership_id: UUID,
    body: MembershipPatch,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.read_metadata")
    if access.role != "student" and "assignment.manage" not in access.capabilities:
        raise HTTPException(status_code=404, detail="Project not found")
    row = (
        await db.execute(
            select(ProjectMembership).where(
                ProjectMembership.id == membership_id,
                ProjectMembership.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Project member not found")
    previous = row.status
    for field in ("status", "capabilities", "content_access", "source_access", "ai_history_access", "expires_at"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    if row.status in {"revoked", "suspended"}:
        row.revoked_at = datetime.now(timezone.utc)
        row.revoked_by = current_user.id
    db.add(
        Event(
            project_id=project_id,
            user_id=current_user.id,
            kind="project_membership_revoked" if row.status == "revoked" else "project_membership_updated",
            data={"membership_id": str(row.id), "role": row.role, "from": previous, "to": row.status},
        )
    )
    await db.commit()
    await db.refresh(row)
    return _membership_dict(row)


@router.post("/projects/{project_id}/review-cycles", status_code=201)
async def submit_review_cycle(
    project_id: UUID,
    body: ReviewSubmit,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.submit_review")
    reviewer = await resolve_project_access(db, project_id, (await db.execute(select(User).where(User.id == body.reviewer_id))).scalar_one_or_none()) if body.reviewer_id else None
    if reviewer is None or "project.approve_chapter" not in reviewer.capabilities:
        raise HTTPException(status_code=404, detail="Reviewer not assigned to this project")
    try:
        row = await submit_for_review(
            db, access.project, current_user.id, body.reviewer_id, access.capabilities,
            scope_type=body.scope_type, scope_id=body.scope_id, deadline=body.deadline,
            resubmitted_from_id=body.resubmitted_from_id,
        )
    except WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _cycle_dict(row)


@router.get("/projects/{project_id}/review-cycles")
async def list_review_cycles(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_project_capability(db, project_id, current_user, "project.read_content")
    rows = list((await db.execute(select(ReviewCycle).where(ReviewCycle.project_id == project_id).order_by(ReviewCycle.cycle_number.desc()))).scalars())
    return [_cycle_dict(row) for row in rows]


@router.get("/projects/{project_id}/review-cycles/{cycle_id}/snapshot")
async def review_snapshot(
    project_id: UUID,
    cycle_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_project_capability(db, project_id, current_user, "project.read_content")
    cycle = (await db.execute(select(ReviewCycle).where(ReviewCycle.id == cycle_id, ReviewCycle.project_id == project_id))).scalar_one_or_none()
    if cycle is None:
        raise HTTPException(status_code=404, detail="Review cycle not found")
    snapshot = (await db.execute(select(DocumentSnapshot).where(DocumentSnapshot.id == cycle.snapshot_id))).scalar_one()
    return {"review_cycle": _cycle_dict(cycle), "snapshot": {"id": snapshot.id, "document_version": snapshot.document_version, "checksum": snapshot.checksum, "canonical_document": snapshot.canonical_document}}


@router.post("/projects/{project_id}/review-cycles/{cycle_id}/decision")
async def review_cycle_decision(
    project_id: UUID,
    cycle_id: UUID,
    body: ReviewDecision,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.approve_chapter")
    cycle = (await db.execute(select(ReviewCycle).where(ReviewCycle.id == cycle_id, ReviewCycle.project_id == project_id))).scalar_one_or_none()
    if cycle is None:
        raise HTTPException(status_code=404, detail="Review cycle not found")
    try:
        approval = await decide_review(db, access.project, cycle, current_user.id, access.capabilities, decision=body.decision, note=body.note)
    except WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"review_cycle": _cycle_dict(cycle), "approval": _approval_dict(approval) if approval else None, "workflow_state": access.project.workflow_state}


@router.post("/projects/{project_id}/comments", status_code=201)
async def add_comment(
    project_id: UUID,
    body: CommentCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.comment")
    try:
        row = await create_comment(db, access.project, current_user.id, anchor_type=body.anchor_type, anchor=body.anchor, body=body.body, review_cycle_id=body.review_cycle_id, parent_id=body.parent_id, assigned_to=body.assigned_to, visibility=body.visibility)
    except WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _comment_dict(row)


@router.get("/projects/{project_id}/comments")
async def list_comments(
    project_id: UUID,
    current_user: CurrentUser,
    status_filter: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    access = await require_project_capability(db, project_id, current_user, "project.read_content")
    query = select(CollaborationComment).where(CollaborationComment.project_id == project_id)
    if status_filter:
        query = query.where(CollaborationComment.status == status_filter)
    rows = list((await db.execute(query.order_by(CollaborationComment.created_at))).scalars())
    result = []
    for row in rows:
        if row.visibility == "private_author" and row.author_id != current_user.id:
            continue
        row.anchor_state = refresh_comment_anchor(access.project, row)
        result.append(_comment_dict(row))
    await db.commit()
    return result


@router.patch("/projects/{project_id}/comments/{comment_id}")
async def patch_comment(
    project_id: UUID,
    comment_id: UUID,
    body: CommentPatch,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.comment")
    row = (await db.execute(select(CollaborationComment).where(CollaborationComment.id == comment_id, CollaborationComment.project_id == project_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if body.action == "resolve":
        row.status = "resolved"; row.resolved_by = current_user.id; row.resolved_at = datetime.now(timezone.utc)
    elif body.action == "reopen":
        row.status = "open"; row.resolved_by = None; row.resolved_at = None
    else:
        if not body.anchor:
            raise HTTPException(status_code=422, detail="Re-anchoring requires an anchor")
        row.anchor = body.anchor
        row.document_version = access.project.document_version
        row.anchor_state = refresh_comment_anchor(access.project, row)
    await db.commit(); await db.refresh(row)
    return _comment_dict(row)


@router.post("/projects/{project_id}/suggestions", status_code=201)
async def add_suggestion(
    project_id: UUID,
    body: SuggestionCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.suggest")
    try:
        row = await create_suggestion(db, access.project, current_user.id, target_block_id=body.target_block_id, proposed_operation=body.proposed_operation, explanation=body.explanation, review_cycle_id=body.review_cycle_id)
    except WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _suggestion_dict(row)


@router.get("/projects/{project_id}/suggestions")
async def list_suggestions(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_project_capability(db, project_id, current_user, "project.read_content")
    rows = list((await db.execute(select(HumanSuggestion).where(HumanSuggestion.project_id == project_id).order_by(HumanSuggestion.created_at.desc()))).scalars())
    return [_suggestion_dict(row) for row in rows]


@router.post("/projects/{project_id}/suggestions/{suggestion_id}/decision")
async def suggestion_decision(
    project_id: UUID,
    suggestion_id: UUID,
    body: SuggestionDecision,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.accept_suggestion")
    row = (await db.execute(select(HumanSuggestion).where(HumanSuggestion.id == suggestion_id, HumanSuggestion.project_id == project_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    try:
        result = await decide_suggestion(db, access.project, row, current_user.id, access.capabilities, decision=body.decision, response=body.response, operation_override=body.operation_override)
    except WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _suggestion_dict(result)


@router.post("/projects/{project_id}/approvals", status_code=201)
async def create_approval(
    project_id: UUID,
    body: ApprovalCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    required = {
        "content": "project.approve_academic", "citation": "source.verify",
        "formatting": "project.approve_formatting", "institutional": "project.transition_submission",
        "submission": "project.transition_submission",
    }[body.dimension]
    access = await require_project_capability(db, project_id, current_user, required)
    if access.project.user_id == current_user.id:
        raise HTTPException(status_code=409, detail="A student cannot approve their own thesis.")
    snapshot = await create_snapshot(db, access.project, current_user.id, name=f"{body.dimension.title()} approval v{access.project.document_version}", reason=f"{body.dimension}_approval", automatic=False)
    row = ApprovalRecord(
        project_id=project_id, review_cycle_id=body.review_cycle_id, snapshot_id=snapshot.id,
        dimension=body.dimension, scope_type=body.scope_type, scope_id=body.scope_id,
        decision=body.decision, status="active", approved_by=current_user.id,
        document_version=access.project.document_version, document_checksum=snapshot.checksum, note=body.note,
    )
    db.add(row)
    if body.dimension == "formatting" and access.project.workflow_state == "formatting_review":
        content_ok = (await db.execute(select(func.count(ApprovalRecord.id)).where(ApprovalRecord.project_id == project_id, ApprovalRecord.dimension == "content", ApprovalRecord.status == "active"))).scalar_one() > 0
        if content_ok:
            access.project.workflow_state = "submission_ready"
    db.add(Event(project_id=project_id, user_id=current_user.id, kind="approval_recorded", data={"approval_id": str(row.id), "dimension": body.dimension, "snapshot_id": str(snapshot.id), "document_version": access.project.document_version}))
    await db.commit(); await db.refresh(row)
    return _approval_dict(row)


@router.get("/projects/{project_id}/approvals")
async def list_approvals(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_project_capability(db, project_id, current_user, "project.read_metadata")
    rows = list((await db.execute(select(ApprovalRecord).where(ApprovalRecord.project_id == project_id).order_by(ApprovalRecord.approved_at.desc()))).scalars())
    return [_approval_dict(row) for row in rows]


@router.post("/projects/{project_id}/instructions", status_code=201)
async def create_instruction(
    project_id: UUID,
    body: InstructionCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.issue_instruction")
    row = await add_supervisor_instruction(db, access.project, current_user.id, scope_type=body.scope_type, scope_id=body.scope_id, instruction_type=body.instruction_type, priority=body.priority, text=body.text, structured=body.structured, due_at=body.due_at)
    return {"id": row.id, "scope_type": row.scope_type, "scope_id": row.scope_id, "instruction_type": row.instruction_type, "priority": row.priority, "text": row.text, "status": row.status, "due_at": row.due_at}


@router.get("/projects/{project_id}/instructions")
async def list_instructions(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_project_capability(db, project_id, current_user, "project.read_content")
    rows = list((await db.execute(select(SupervisorInstruction).where(SupervisorInstruction.project_id == project_id).order_by(SupervisorInstruction.created_at.desc()))).scalars())
    return [{"id": row.id, "author_id": row.author_id, "scope_type": row.scope_type, "scope_id": row.scope_id, "instruction_type": row.instruction_type, "priority": row.priority, "text": row.text, "structured": row.structured, "status": row.status, "due_at": row.due_at, "created_at": row.created_at} for row in rows]


@router.post("/projects/{project_id}/assignments", status_code=201)
async def create_assignment(
    project_id: UUID,
    body: AssignmentCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "assignment.manage")
    assignee = await resolve_project_access(db, project_id, (await db.execute(select(User).where(User.id == body.assignee_id))).scalar_one_or_none())
    if assignee is None:
        raise HTTPException(status_code=404, detail="Assignee not found")
    row = ReviewAssignment(project_id=project_id, assignee_id=body.assignee_id, assigned_by=current_user.id, assignment_type=body.assignment_type, scope=body.scope, priority=body.priority, due_at=body.due_at)
    db.add(row); await db.commit(); await db.refresh(row)
    return {"id": row.id, "assignee_id": row.assignee_id, "assignment_type": row.assignment_type, "scope": row.scope, "status": row.status, "priority": row.priority, "due_at": row.due_at}


@router.get("/collaboration/queue")
async def my_queue(
    current_user: CurrentUser,
    status_filter: str = Query("open", alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = list((await db.execute(select(ReviewAssignment).where(ReviewAssignment.assignee_id == current_user.id, ReviewAssignment.status == status_filter).order_by(ReviewAssignment.due_at.asc().nullslast(), ReviewAssignment.created_at))).scalars())
    return [{"id": row.id, "project_id": row.project_id, "assignment_type": row.assignment_type, "scope": row.scope, "status": row.status, "priority": row.priority, "due_at": row.due_at, "created_at": row.created_at} for row in rows]


@router.post("/projects/{project_id}/handoffs", status_code=201)
async def create_handoff(
    project_id: UUID,
    body: HandoffCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_project_capability(db, project_id, current_user, "assignment.manage")
    new_access = await resolve_project_access(db, project_id, (await db.execute(select(User).where(User.id == body.new_user_id))).scalar_one_or_none())
    if new_access is None:
        raise HTTPException(status_code=404, detail="New assignee not found")
    row = ProjectHandoff(project_id=project_id, previous_user_id=body.previous_user_id, new_user_id=body.new_user_id, role=body.role, reason=body.reason, outstanding_items=body.outstanding_items, effective_at=body.effective_at or datetime.now(timezone.utc), created_by=current_user.id)
    db.add(row); db.add(Event(project_id=project_id, user_id=current_user.id, kind="project_handoff_recorded", data={"handoff_id": str(row.id), "previous_user_id": str(body.previous_user_id) if body.previous_user_id else None, "new_user_id": str(body.new_user_id), "role": body.role, "outstanding_items": body.outstanding_items}))
    await db.commit(); await db.refresh(row)
    return {"id": row.id, "previous_user_id": row.previous_user_id, "new_user_id": row.new_user_id, "role": row.role, "reason": row.reason, "effective_at": row.effective_at}


@router.post("/projects/{project_id}/workflow/transition")
async def workflow_transition(
    project_id: UUID,
    body: TransitionRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.read_metadata")
    try:
        await transition_project(db, access.project, current_user.id, body.target, access.capabilities, note=body.note)
    except WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return {"project_id": project_id, "workflow_state": access.project.workflow_state}


@router.get("/projects/{project_id}/audit-timeline")
async def audit_timeline(
    project_id: UUID,
    current_user: CurrentUser,
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_project_capability(db, project_id, current_user, "project.read_metadata")
    return await project_timeline(db, project_id, limit=limit)


@router.get("/notifications")
async def list_notifications(
    current_user: CurrentUser,
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    rows = list((await db.execute(query.order_by(Notification.created_at.desc()).limit(200))).scalars())
    return [{"id": row.id, "project_id": row.project_id, "kind": row.kind, "title": row.title, "body": row.body, "data": row.data, "read_at": row.read_at, "created_at": row.created_at} for row in rows]


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (await db.execute(select(Notification).where(Notification.id == notification_id, Notification.user_id == current_user.id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    row.read_at = datetime.now(timezone.utc); await db.commit()
    return {"id": row.id, "read_at": row.read_at}


@router.put("/notification-preferences")
async def set_notification_preference(
    body: NotificationPreferencePatch,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (await db.execute(select(NotificationPreference).where(NotificationPreference.user_id == current_user.id, NotificationPreference.kind == body.kind))).scalar_one_or_none()
    if row is None:
        row = NotificationPreference(user_id=current_user.id, kind=body.kind)
        db.add(row)
    row.cadence = body.cadence; row.email_enabled = body.email_enabled; row.content_preview = body.content_preview
    await db.commit(); await db.refresh(row)
    return {"kind": row.kind, "cadence": row.cadence, "email_enabled": row.email_enabled, "content_preview": row.content_preview}
