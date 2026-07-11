"""Fast Phase 4 authority, workflow, anchor and governance invariants."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.canonical.model import ThesisDocument
from app.collaboration.capabilities import ROLE_CAPABILITIES, STUDENT_CAPABILITIES
from app.collaboration.editor_hooks import affected_dimensions
from app.collaboration.governance import GovernanceError, profile_impact, validate_policy
from app.collaboration.workflow import (
    WorkflowError,
    block_text,
    find_block,
    refresh_comment_anchor,
    require_transition,
)
from app.models.project import Project
from app.models.review_collaboration import CollaborationComment


def _project() -> Project:
    document = ThesisDocument.model_validate(
        {
            "meta": {"title": "Institutional Memory"},
            "front_matter": [],
            "chapters": [
                {
                    "number": 1,
                    "title": "Introduction",
                    "status": "in_progress",
                    "blocks": [
                        {
                            "type": "paragraph",
                            "runs": [{"text": "Memory becomes an institutional practice."}],
                        }
                    ],
                }
            ],
            "works_cited": [],
        }
    )
    payload = document.model_dump(mode="json")
    return Project(
        id=uuid4(),
        user_id=uuid4(),
        institution_id=uuid4(),
        title="Institutional Memory",
        workflow_state="student_review",
        document_version=8,
        canonical_schema_version=document.schema_version,
        meta=payload["meta"],
        front_matter=payload["front_matter"],
        chapters=payload["chapters"],
        works_cited=payload["works_cited"],
    )


def test_roles_separate_author_review_format_and_administration() -> None:
    student = STUDENT_CAPABILITIES
    supervisor = ROLE_CAPABILITIES["supervisor"]
    operator = ROLE_CAPABILITIES["operator"]
    admin = ROLE_CAPABILITIES["institution_admin"]

    assert "project.edit_content" in student
    assert "project.approve_academic" not in student
    assert "project.approve_academic" in supervisor
    assert "project.edit_content" not in supervisor
    assert "project.approve_formatting" in operator
    assert "project.approve_academic" not in operator
    assert "policy.manage" in admin
    assert "project.read_content" not in admin
    assert "project.read_ai_history" not in supervisor


def test_state_machine_requires_role_capability() -> None:
    project = _project()
    with pytest.raises(WorkflowError, match="cannot perform"):
        require_transition(project, "supervisor_review", {"project.read_content"})
    require_transition(project, "supervisor_review", {"project.submit_review"})

    project.workflow_state = "supervisor_review"
    with pytest.raises(WorkflowError):
        require_transition(project, "submission_ready", ROLE_CAPABILITIES["supervisor"])
    require_transition(project, "academically_approved", ROLE_CAPABILITIES["supervisor"])


def test_governance_policy_rejects_default_admin_read_and_autonomous_generation() -> None:
    with pytest.raises(GovernanceError, match="default manuscript-content"):
        validate_policy({"privacy": {"admin_content_access_default": True}})
    with pytest.raises(GovernanceError, match="full-section"):
        validate_policy({"ai_policy": {"full_section_generation": True}})
    safe = validate_policy({"workflow": {"format_review_required": False}})
    assert safe["privacy"]["admin_content_access_default"] is False
    assert safe["workflow"]["format_review_required"] is False


def test_profile_impact_is_versioned_and_never_auto_applied() -> None:
    impact = profile_impact(
        {"margin_left": 1.25, "ai_disclosure_required": False},
        {"margin_left": 1.5, "ai_disclosure_required": True},
    )
    assert impact["changed_fields"] == 2
    assert impact["requires_preview_regeneration"] is True
    assert impact["requires_formatting_reapproval"] is True


def test_comment_anchor_preserves_selected_text_and_relocates_once() -> None:
    project = _project()
    document = ThesisDocument.model_validate(
        {
            "schema_version": project.canonical_schema_version,
            "meta": project.meta,
            "front_matter": project.front_matter,
            "chapters": project.chapters,
            "works_cited": project.works_cited,
        }
    )
    block = document.chapters[0].blocks[0]
    text = block_text(block.model_dump(mode="json"))
    selected = "institutional practice"
    start = text.index(selected)
    comment = CollaborationComment(
        id=uuid4(),
        project_id=project.id,
        author_id=uuid4(),
        anchor_type="block_range",
        anchor={"block_id": str(block.id), "start_offset": start, "end_offset": start + len(selected)},
        selected_text_snapshot=selected,
        document_version=project.document_version,
        body="Clarify this phrase.",
    )
    assert refresh_comment_anchor(project, comment) == "current"

    project.chapters[0]["blocks"][0]["runs"][0]["text"] = "The chapter shows how institutional practice emerges through memory."
    assert refresh_comment_anchor(project, comment) == "moved_successfully"
    assert comment.anchor["start_offset"] == project.chapters[0]["blocks"][0]["runs"][0]["text"].index(selected)


def test_canonical_commands_invalidate_only_relevant_approval_dimensions() -> None:
    assert affected_dimensions("update_block_text") == {"content", "citation", "submission"}
    assert affected_dimensions("update_metadata") == {"formatting", "institutional", "submission"}
    assert affected_dimensions("move_block") == {"content", "citation", "formatting", "submission"}
