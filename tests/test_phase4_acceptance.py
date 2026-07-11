"""End-to-end Phase 4 institutional collaboration acceptance demonstration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.export import Export
from app.models.institution import Institution
from app.models.project import Project
from app.models.tenancy import Department, OrganizationMembership, ProjectMembership
from app.models.user import User
from tests.conftest import auth_cookie


pytestmark = pytest.mark.asyncio


async def _person(db: AsyncSession, institution: Institution, name: str) -> User:
    row = User(
        email=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:6]}@test.edu",
        full_name=name,
        institution_id=institution.id,
        affiliation_status="domain_verified",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _grant(
    db: AsyncSession,
    institution: Institution,
    department: Department,
    project_id,
    user: User,
    student: User,
    role: str,
    *,
    capabilities: list[str] | None = None,
    content: bool = True,
    sources: bool = True,
) -> None:
    db.add(
        OrganizationMembership(
            institution_id=institution.id,
            department_id=department.id,
            user_id=user.id,
            role=role,
            affiliation_status="admin_verified",
            status="active",
            verified_by=student.id,
            verified_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        ProjectMembership(
            project_id=project_id,
            user_id=user.id,
            role=role,
            capabilities=capabilities or [],
            content_access=content,
            source_access=sources,
            ai_history_access=False,
            granted_by=student.id,
        )
    )
    await db.commit()


async def test_full_collaborative_thesis_submission_flow(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
    user_a: User,
) -> None:
    department = Department(
        institution_id=test_institution.id,
        name="PG & Research Department of English",
        code="ENG",
        created_by=user_a.id,
    )
    db_session.add(department)
    await db_session.commit()
    await db_session.refresh(department)

    supervisor = await _person(db_session, test_institution, "Dr Maria")
    operator = await _person(db_session, test_institution, "Formatting Operator")
    admin = await _person(db_session, test_institution, "Department Coordinator")

    created = await client.post(
        "/projects",
        json={
            "title": "Memory as Narrative Resistance",
            "mode": "student",
            "format_profile": "mla_strict",
        },
        cookies=auth_cookie(user_a),
    )
    assert created.status_code == 201
    project_id = created.json()["id"]
    project_row = (
        await db_session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one()
    project_row.institution_id = test_institution.id
    project_row.department_id = department.id
    project_row.workflow_state = "student_review"
    await db_session.commit()

    seeded = await client.patch(
        f"/projects/{project_id}/chapters",
        json={
            "expected_version": project_row.document_version,
            "chapters": [
                {
                    "number": 3,
                    "title": "Memory as Narrative Resistance",
                    "status": "in_progress",
                    "blocks": [
                        {
                            "type": "paragraph",
                            "runs": [
                                {
                                    "text": (
                                        "The house is described as a place of memory, but the "
                                        "paragraph does not yet explain its argumentative function."
                                    )
                                }
                            ],
                        }
                    ],
                }
            ],
        },
        cookies=auth_cookie(user_a),
    )
    assert seeded.status_code == 200
    chapter = seeded.json()["chapters"][0]
    block = chapter["blocks"][0]

    await _grant(
        db_session,
        test_institution,
        department,
        project_id,
        supervisor,
        user_a,
        "supervisor",
        capabilities=["source.verify"],
    )
    await _grant(
        db_session,
        test_institution,
        department,
        project_id,
        operator,
        user_a,
        "operator",
    )
    db_session.add(
        OrganizationMembership(
            institution_id=test_institution.id,
            department_id=department.id,
            user_id=admin.id,
            role="department_admin",
            affiliation_status="admin_verified",
            status="active",
            verified_by=user_a.id,
            verified_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    first_submit = await client.post(
        f"/projects/{project_id}/review-cycles",
        json={
            "reviewer_id": str(supervisor.id),
            "scope_type": "chapter",
            "scope_id": chapter["id"],
            "deadline": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        },
        cookies=auth_cookie(user_a),
    )
    assert first_submit.status_code == 201
    first_cycle = first_submit.json()

    selected = "described as a place of memory"
    paragraph = block["runs"][0]["text"]
    start = paragraph.index(selected)
    comment = await client.post(
        f"/projects/{project_id}/comments",
        json={
            "anchor_type": "block_range",
            "anchor": {
                "block_id": block["id"],
                "start_offset": start,
                "end_offset": start + len(selected),
                "selected_text_snapshot": selected,
            },
            "body": "Explain how this description advances the chapter claim.",
            "review_cycle_id": first_cycle["id"],
            "assigned_to": str(user_a.id),
        },
        cookies=auth_cookie(supervisor),
    )
    assert comment.status_code == 201

    revised_text = (
        "The house converts private memory into narrative resistance, linking domestic space "
        "to the chapter's argument about inherited authority."
    )
    suggestion = await client.post(
        f"/projects/{project_id}/suggestions",
        json={
            "target_block_id": block["id"],
            "review_cycle_id": first_cycle["id"],
            "explanation": "Connect the description explicitly to the chapter claim.",
            "proposed_operation": {
                "command_type": "update_block_text",
                "payload": {"block_id": block["id"], "text": revised_text},
            },
        },
        cookies=auth_cookie(supervisor),
    )
    assert suggestion.status_code == 201

    accepted = await client.post(
        f"/projects/{project_id}/suggestions/{suggestion.json()['id']}/decision",
        json={
            "decision": "accepted",
            "response": "I accept the argument connection and will defend it in the viva.",
        },
        cookies=auth_cookie(user_a),
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["applied_command_id"]

    old_decision = await client.post(
        f"/projects/{project_id}/review-cycles/{first_cycle['id']}/decision",
        json={
            "decision": "approved",
            "note": "The submitted snapshot was academically sound.",
        },
        cookies=auth_cookie(supervisor),
    )
    assert old_decision.status_code == 200
    assert old_decision.json()["approval"]["status"] == "snapshot_only"

    current_project = await client.get(
        f"/projects/{project_id}", cookies=auth_cookie(user_a)
    )
    assert current_project.status_code == 200

    second_submit = await client.post(
        f"/projects/{project_id}/review-cycles",
        json={
            "reviewer_id": str(supervisor.id),
            "scope_type": "project",
            "resubmitted_from_id": first_cycle["id"],
        },
        cookies=auth_cookie(user_a),
    )
    assert second_submit.status_code == 201
    second_cycle = second_submit.json()

    instruction = await client.post(
        f"/projects/{project_id}/instructions",
        json={
            "scope_type": "project",
            "instruction_type": "approved_thesis_statement",
            "priority": "mandatory",
            "text": "Keep the revised central claim unchanged during formatting.",
        },
        cookies=auth_cookie(supervisor),
    )
    assert instruction.status_code == 201

    current_approval = await client.post(
        f"/projects/{project_id}/review-cycles/{second_cycle['id']}/decision",
        json={
            "decision": "approved",
            "note": "Academic content approved for formatting.",
        },
        cookies=auth_cookie(supervisor),
    )
    assert current_approval.status_code == 200
    assert current_approval.json()["approval"]["status"] == "active"
    assert current_approval.json()["workflow_state"] == "academically_approved"

    blocked_rewrite = await client.post(
        f"/projects/{project_id}/collaboration/commands",
        json={
            "command_type": "update_block_text",
            "payload": {"block_id": block["id"], "text": "Operator-authored prose"},
            "expected_document_version": current_project.json()["document_version"] + 1,
        },
        cookies=auth_cookie(operator),
    )
    assert blocked_rewrite.status_code == 409

    latest = await client.get(f"/projects/{project_id}", cookies=auth_cookie(user_a))
    operator_fix = await client.post(
        f"/projects/{project_id}/collaboration/commands",
        json={
            "command_type": "update_metadata",
            "payload": {"path": "submission.year", "value": 2026},
            "expected_document_version": latest.json()["document_version"],
            "client_request_id": f"operator-format-{uuid4()}",
            "summary": "Correct submission year",
        },
        cookies=auth_cookie(operator),
    )
    assert operator_fix.status_code == 200
    assert operator_fix.json()["authority"]["operator_prose_rewrite_allowed"] is False

    to_formatting = await client.post(
        f"/projects/{project_id}/workflow/transition",
        json={"target": "formatting_review", "note": "Academic review completed."},
        cookies=auth_cookie(operator),
    )
    assert to_formatting.status_code == 200

    citation_approval = await client.post(
        f"/projects/{project_id}/approvals",
        json={
            "dimension": "citation",
            "scope_type": "project",
            "decision": "approved",
            "note": "Registered evidence and citation traceability reviewed.",
            "review_cycle_id": second_cycle["id"],
        },
        cookies=auth_cookie(supervisor),
    )
    assert citation_approval.status_code == 201

    formatting_approval = await client.post(
        f"/projects/{project_id}/approvals",
        json={
            "dimension": "formatting",
            "scope_type": "project",
            "decision": "approved",
            "note": "Institutional presentation verified without rewriting academic prose.",
        },
        cookies=auth_cookie(operator),
    )
    assert formatting_approval.status_code == 201

    institutional_approval = await client.post(
        f"/projects/{project_id}/approvals",
        json={
            "dimension": "institutional",
            "scope_type": "project",
            "decision": "approved",
            "note": (
                "Workflow approval recorded; this is not represented as a legal signature."
            ),
        },
        cookies=auth_cookie(admin),
    )
    assert institutional_approval.status_code == 201

    student_attestation = await client.post(
        f"/projects/{project_id}/attestations",
        json={
            "attestation_type": "student_authorship",
            "statement_version": "2026.1",
            "statement_text": "I remain the author and reviewed all accepted assistance.",
            "accepted": True,
        },
        cookies=auth_cookie(user_a),
    )
    assert student_attestation.status_code == 201
    supervisor_attestation = await client.post(
        f"/projects/{project_id}/attestations",
        json={
            "attestation_type": "supervisor_workflow_approval",
            "statement_version": "2026.1",
            "statement_text": (
                "I reviewed and approved the recorded academic submission workflow."
            ),
            "accepted": True,
        },
        cookies=auth_cookie(supervisor),
    )
    assert supervisor_attestation.status_code == 201

    final_project = (
        await db_session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one()
    for fmt in ("docx", "pdf"):
        db_session.add(
            Export(
                project_id=final_project.id,
                user_id=user_a.id,
                format=fmt,
                document_version=final_project.document_version,
                profile_version="institutional:test",
                storage_key=f"exports/test/{project_id}/final.{fmt}",
                checksum=(fmt * 64)[:64],
                size_bytes=2048,
                status="ready",
                report={"pass": True},
                manifest={
                    "state": "final",
                    "document_version": final_project.document_version,
                },
            )
        )
    await db_session.commit()

    readiness = await client.get(
        f"/projects/{project_id}/submission-readiness",
        cookies=auth_cookie(admin),
    )
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is True

    sealed = await client.post(
        f"/projects/{project_id}/submission-packages",
        json={"note": "Department submission package"},
        cookies=auth_cookie(admin),
    )
    assert sealed.status_code == 201
    package = sealed.json()
    assert package["state"] == "sealed"
    assert package["package_checksum"]
    assert package["manifest"]["signature_claim"].startswith(
        "Authenticated workflow approval"
    )

    external = await client.post(
        f"/projects/{project_id}/submission-packages/{package['id']}/external-review",
        json={
            "recipient_email": "examiner@example.edu",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
            "permissions": ["sealed.read_metadata", "sealed.read_content"],
            "download_allowed": False,
            "watermark": "Confidential external examination copy",
        },
        cookies=auth_cookie(admin),
    )
    assert external.status_code == 201
    token = external.json()["access_token"]

    wrong_recipient = await client.post(
        "/external-review/access",
        json={"token": token, "recipient_email": "other@example.edu"},
    )
    assert wrong_recipient.status_code == 404

    external_view = await client.post(
        "/external-review/access",
        json={"token": token, "recipient_email": "examiner@example.edu"},
    )
    assert external_view.status_code == 200
    assert external_view.json()["grant"]["download_allowed"] is False
    assert external_view.json()["canonical_document"]["chapters"]
    assert all(
        "storage_key" not in item
        for item in external_view.json()["submission"]["manifest"]["exports"]
    )

    locked_edit = await client.post(
        f"/projects/{project_id}/collaboration/commands",
        json={
            "command_type": "update_metadata",
            "payload": {"path": "submission.month", "value": "August"},
            "expected_document_version": final_project.document_version,
        },
        cookies=auth_cookie(user_a),
    )
    assert locked_edit.status_code == 409

    timeline = await client.get(
        f"/projects/{project_id}/audit-timeline",
        cookies=auth_cookie(admin),
    )
    assert timeline.status_code == 200
    kinds = {row["kind"] for row in timeline.json()}
    assert {
        "review_cycle_submitted",
        "human_suggestion_decided",
        "submission_package_sealed",
    }.issubset(kinds)

    admin_access = await client.get(
        f"/projects/{project_id}/collaboration/access",
        cookies=auth_cookie(admin),
    )
    assert admin_access.json()["content_access"] is False
    assert admin_access.json()["ai_history_access"] is False
