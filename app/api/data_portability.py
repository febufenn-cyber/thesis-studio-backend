"""Structured data portability without bypassing content or AI-history permissions."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.canonical.migrations import project_payload
from app.collaboration.audit import project_timeline
from app.collaboration.capabilities import require_project_capability
from app.db.deps import get_db
from app.models.ai_message import AIMessage
from app.models.ai_thread import AIThread
from app.models.institutional_governance import SubmissionPackage
from app.models.review_collaboration import (
    ApprovalRecord,
    CollaborationComment,
    HumanSuggestion,
    ReviewCycle,
    SupervisorInstruction,
)
from app.models.tenancy import (
    DataLifecycleRequest,
    NotificationPreference,
    OrganizationMembership,
    ProjectMembership,
)


router = APIRouter(tags=["data-portability"])


def _json_row(row, fields: tuple[str, ...]) -> dict:
    return {field: getattr(row, field) for field in fields}


@router.get("/projects/{project_id}/data-export")
async def export_project_data(
    project_id: UUID,
    current_user: CurrentUser,
    include_ai_history: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(
        db, project_id, current_user, "project.read_metadata"
    )
    project = access.project
    cycles = list(
        (
            await db.execute(
                select(ReviewCycle)
                .where(ReviewCycle.project_id == project_id)
                .order_by(ReviewCycle.cycle_number)
            )
        ).scalars()
    )
    comments = list(
        (
            await db.execute(
                select(CollaborationComment)
                .where(CollaborationComment.project_id == project_id)
                .order_by(CollaborationComment.created_at)
            )
        ).scalars()
    )
    suggestions = list(
        (
            await db.execute(
                select(HumanSuggestion)
                .where(HumanSuggestion.project_id == project_id)
                .order_by(HumanSuggestion.created_at)
            )
        ).scalars()
    )
    approvals = list(
        (
            await db.execute(
                select(ApprovalRecord)
                .where(ApprovalRecord.project_id == project_id)
                .order_by(ApprovalRecord.approved_at)
            )
        ).scalars()
    )
    instructions = list(
        (
            await db.execute(
                select(SupervisorInstruction)
                .where(SupervisorInstruction.project_id == project_id)
                .order_by(SupervisorInstruction.created_at)
            )
        ).scalars()
    )
    packages = list(
        (
            await db.execute(
                select(SubmissionPackage)
                .where(SubmissionPackage.project_id == project_id)
                .order_by(SubmissionPackage.package_number)
            )
        ).scalars()
    )
    memberships = list(
        (
            await db.execute(
                select(ProjectMembership)
                .where(ProjectMembership.project_id == project_id)
                .order_by(ProjectMembership.created_at)
            )
        ).scalars()
    )

    private_ai: list[dict] = []
    ai_included = include_ai_history and access.ai_history_access
    if ai_included:
        threads = list(
            (
                await db.execute(
                    select(AIThread)
                    .where(AIThread.project_id == project_id)
                    .order_by(AIThread.created_at)
                )
            ).scalars()
        )
        for thread in threads:
            messages = list(
                (
                    await db.execute(
                        select(AIMessage)
                        .where(AIMessage.thread_id == thread.id)
                        .order_by(AIMessage.created_at)
                    )
                ).scalars()
            )
            private_ai.append(
                {
                    "thread": {
                        "id": thread.id,
                        "title": thread.title,
                        "scope": thread.scope,
                        "private": thread.private,
                        "created_at": thread.created_at,
                    },
                    "messages": [
                        {
                            "id": row.id,
                            "role": row.role,
                            "task_mode": row.task_mode,
                            "content": row.content,
                            "structured": row.structured,
                            "scope": row.scope,
                            "document_version": row.document_version,
                            "model": row.model,
                            "prompt_name": row.prompt_name,
                            "prompt_version": row.prompt_version,
                            "created_at": row.created_at,
                        }
                        for row in messages
                    ],
                }
            )

    return {
        "schema": "robofox.project-data-export.v1",
        "generated_at": datetime.now(timezone.utc),
        "requester": {
            "user_id": current_user.id,
            "role": access.role,
            "content_access": access.content_access,
            "source_access": access.source_access,
            "ai_history_access": access.ai_history_access,
        },
        "project": {
            "id": project.id,
            "student_author_id": project.user_id,
            "institution_id": project.institution_id,
            "department_id": project.department_id,
            "title": project.title,
            "workflow_state": project.workflow_state,
            "document_version": project.document_version,
            "format_profile": project.format_profile,
            "institutional_profile_version_id": project.institutional_profile_version_id,
            "institutional_policy_version_id": project.institutional_policy_version_id,
            "submission_locked": project.submission_locked,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        },
        "canonical_document": project_payload(project) if access.content_access else None,
        "review_cycles": [
            _json_row(
                row,
                (
                    "id", "snapshot_id", "cycle_number", "scope_type", "scope_id",
                    "submitted_document_version", "submitted_checksum", "submitted_by",
                    "reviewer_id", "status", "decision", "decision_note", "deadline",
                    "submitted_at", "decided_at",
                ),
            )
            for row in cycles
        ] if access.content_access else [],
        "comments": [
            _json_row(
                row,
                (
                    "id", "review_cycle_id", "author_id", "anchor_type", "anchor",
                    "selected_text_snapshot", "document_version", "anchor_state", "body",
                    "visibility", "status", "assigned_to", "created_at", "resolved_at",
                ),
            )
            for row in comments
            if access.content_access
            and (row.visibility != "private_author" or row.author_id == current_user.id)
        ],
        "suggestions": [
            _json_row(
                row,
                (
                    "id", "review_cycle_id", "author_id", "target_block_id",
                    "based_on_document_version", "before_block", "proposed_operation",
                    "explanation", "status", "student_response", "decision_by",
                    "decision_at", "applied_command_id", "created_at",
                ),
            )
            for row in suggestions
        ] if access.content_access else [],
        "approvals": [
            _json_row(
                row,
                (
                    "id", "review_cycle_id", "snapshot_id", "dimension", "scope_type",
                    "scope_id", "decision", "status", "approved_by", "document_version",
                    "document_checksum", "note", "invalidated_reason", "approved_at",
                    "invalidated_at",
                ),
            )
            for row in approvals
        ],
        "supervisor_instructions": [
            _json_row(
                row,
                (
                    "id", "author_id", "scope_type", "scope_id", "instruction_type",
                    "priority", "text", "structured", "status", "due_at", "created_at",
                ),
            )
            for row in instructions
        ] if access.content_access else [],
        "memberships": [
            _json_row(
                row,
                (
                    "id", "user_id", "role", "status", "capabilities", "content_access",
                    "source_access", "ai_history_access", "expires_at", "revoked_at",
                    "created_at",
                ),
            )
            for row in memberships
        ],
        "submission_packages": [
            {
                "id": row.id,
                "package_number": row.package_number,
                "state": row.state,
                "document_version": row.document_version,
                "document_checksum": row.document_checksum,
                "package_checksum": row.package_checksum,
                "profile_version_id": row.profile_version_id,
                "policy_version_id": row.policy_version_id,
                "sealed_at": row.sealed_at,
                "withdrawn_at": row.withdrawn_at,
            }
            for row in packages
        ],
        "audit_timeline": await project_timeline(db, project_id, limit=500),
        "private_ai_history": private_ai,
        "private_ai_history_included": ai_included,
        "private_ai_history_reason": (
            "included by explicit request and capability"
            if ai_included
            else "not requested or requester lacks project.read_ai_history"
        ),
        "binary_notice": (
            "This structured export lists immutable package and export checksums. "
            "Original uploads and rendered binaries remain downloadable through their "
            "normal authenticated endpoints and are not embedded in this JSON response."
        ),
    }


@router.get("/account/data-export")
async def export_account_data(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    organizations = list(
        (
            await db.execute(
                select(OrganizationMembership)
                .where(OrganizationMembership.user_id == current_user.id)
                .order_by(OrganizationMembership.created_at)
            )
        ).scalars()
    )
    projects = list(
        (
            await db.execute(
                select(ProjectMembership)
                .where(ProjectMembership.user_id == current_user.id)
                .order_by(ProjectMembership.created_at)
            )
        ).scalars()
    )
    preferences = list(
        (
            await db.execute(
                select(NotificationPreference)
                .where(NotificationPreference.user_id == current_user.id)
                .order_by(NotificationPreference.kind)
            )
        ).scalars()
    )
    lifecycle = list(
        (
            await db.execute(
                select(DataLifecycleRequest)
                .where(DataLifecycleRequest.user_id == current_user.id)
                .order_by(DataLifecycleRequest.requested_at)
            )
        ).scalars()
    )
    return {
        "schema": "robofox.account-data-export.v1",
        "generated_at": datetime.now(timezone.utc),
        "identity": {
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "register_number": current_user.register_number,
            "identity_provider": current_user.identity_provider,
            "account_status": current_user.account_status,
            "claimed_institution_id": current_user.institution_id,
            "affiliation_status": current_user.affiliation_status,
            "created_at": current_user.created_at,
            "last_login_at": current_user.last_login_at,
        },
        "organization_memberships": [
            _json_row(
                row,
                (
                    "id", "institution_id", "department_id", "role",
                    "affiliation_status", "status", "capability_overrides",
                    "verified_at", "suspended_at", "created_at",
                ),
            )
            for row in organizations
        ],
        "project_memberships": [
            _json_row(
                row,
                (
                    "id", "project_id", "role", "status", "capabilities",
                    "content_access", "source_access", "ai_history_access",
                    "expires_at", "revoked_at", "created_at",
                ),
            )
            for row in projects
        ],
        "notification_preferences": [
            _json_row(
                row,
                ("kind", "cadence", "email_enabled", "content_preview", "updated_at"),
            )
            for row in preferences
        ],
        "data_lifecycle_requests": [
            _json_row(
                row,
                (
                    "id", "institution_id", "project_id", "request_type", "status",
                    "reason", "legal_hold", "requested_at", "execute_after",
                    "completed_at", "result",
                ),
            )
            for row in lifecycle
        ],
        "retention_notice": (
            "Active-system deletion and encrypted-backup expiry may occur on different "
            "schedules according to the institution's published retention policy."
        ),
    }
