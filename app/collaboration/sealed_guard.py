"""ORM guard that freezes canonical thesis fields while a submission is sealed."""

from __future__ import annotations

from sqlalchemy import event, inspect

from app.models.project import Project


_CANONICAL_FIELDS = {
    "meta",
    "front_matter",
    "chapters",
    "works_cited",
    "document_version",
    "canonical_schema_version",
    "active_revision_id",
}


class SealedProjectMutationError(RuntimeError):
    pass


@event.listens_for(Project, "before_update")
def prevent_sealed_canonical_mutation(mapper, connection, project: Project) -> None:  # noqa: ARG001
    """Reject canonical changes regardless of which legacy/new endpoint initiated them.

    Withdrawal or a post-submission revision first clears ``submission_locked`` in
    its own governed transaction. Merely changing workflow metadata or reading the
    sealed project remains allowed.
    """

    if not project.submission_locked:
        return
    state = inspect(project)
    changed = [
        field
        for field in sorted(_CANONICAL_FIELDS)
        if state.attrs[field].history.has_changes()
    ]
    if changed:
        raise SealedProjectMutationError(
            "The sealed submission is immutable. Withdraw it or start a governed "
            "post-submission revision before changing: " + ", ".join(changed)
        )
