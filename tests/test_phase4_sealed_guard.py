"""Phase 4 sealed-package immutability invariants."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import inspect

from app.collaboration.sealed_guard import (
    SealedProjectMutationError,
    prevent_sealed_canonical_mutation,
)
from app.models.project import Project


def _sealed_project() -> Project:
    row = Project(
        id=uuid4(),
        user_id=uuid4(),
        institution_id=uuid4(),
        title="Sealed Thesis",
        document_version=12,
        meta={"title": "Sealed Thesis"},
        front_matter=[],
        chapters=[],
        works_cited=[],
        submission_locked=True,
    )
    # Simulate a loaded clean ORM object before the attempted mutation.
    state = inspect(row)
    state._commit_all(state.dict)
    return row


def test_sealed_project_rejects_canonical_changes() -> None:
    row = _sealed_project()
    row.meta = {"title": "Changed after submission"}
    with pytest.raises(SealedProjectMutationError, match="sealed submission is immutable"):
        prevent_sealed_canonical_mutation(None, None, row)


def test_sealed_project_allows_operational_workflow_metadata() -> None:
    row = _sealed_project()
    row.workflow_state = "submitted"
    prevent_sealed_canonical_mutation(None, None, row)


def test_withdrawn_project_can_start_post_submission_revision() -> None:
    row = _sealed_project()
    row.submission_locked = False
    row.meta = {"title": "Post-viva corrected thesis"}
    prevent_sealed_canonical_mutation(None, None, row)
