"""Transactional orchestration for Phase 2 structured editing."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.canonical.migrations import apply_payload, project_payload
from app.canonical.model import ThesisDocument
from app.editor.commands import CommandError, CommandResult, apply_command
from app.models.citation_resolution import CitationResolution
from app.models.document_command import DocumentCommand
from app.models.document_snapshot import DocumentSnapshot
from app.models.event import Event
from app.models.manuscript_revision import ManuscriptRevision
from app.models.project import Project
from app.models.quote import Quote
from app.models.review_item import ReviewItem


AUTO_SNAPSHOT_EVERY = 25


class VersionConflict(RuntimeError):
    def __init__(self, expected: int, current: int):
        self.expected = expected
        self.current = current
        super().__init__("Project changed in another session. Reload before saving.")


class UndoConflict(RuntimeError):
    pass


def _canonical_checksum(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _document(project: Project) -> ThesisDocument:
    return ThesisDocument.model_validate(project_payload(project))


async def create_snapshot(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    *,
    name: str,
    reason: str,
    automatic: bool,
) -> DocumentSnapshot:
    payload = project_payload(project)
    snapshot = DocumentSnapshot(
        project_id=project.id,
        user_id=user_id,
        manuscript_revision_id=project.active_revision_id,
        name=name[:180],
        reason=reason[:60],
        automatic=automatic,
        document_version=project.document_version,
        canonical_document=payload,
        checksum=_canonical_checksum(payload),
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


async def _ensure_initial_snapshot(db: AsyncSession, project: Project, user_id: UUID) -> None:
    exists = (
        await db.execute(
            select(DocumentSnapshot.id)
            .where(DocumentSnapshot.project_id == project.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if exists is None:
        await create_snapshot(
            db,
            project,
            user_id,
            name="Initial editor checkpoint",
            reason="editor_opened",
            automatic=True,
        )


async def _maybe_periodic_snapshot(db: AsyncSession, project: Project, user_id: UUID) -> None:
    if project.document_version % AUTO_SNAPSHOT_EVERY != 0:
        return
    existing = (
        await db.execute(
            select(DocumentSnapshot.id).where(
                DocumentSnapshot.project_id == project.id,
                DocumentSnapshot.document_version == project.document_version,
                DocumentSnapshot.automatic.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        await create_snapshot(
            db,
            project,
            user_id,
            name=f"Automatic checkpoint v{project.document_version}",
            reason="periodic",
            automatic=True,
        )


async def _original_block(project: Project, db: AsyncSession, block_id: str) -> dict:
    if not project.active_revision_id:
        raise CommandError("No active imported manuscript is available for restoration.")
    revision = (
        await db.execute(
            select(ManuscriptRevision).where(
                ManuscriptRevision.id == project.active_revision_id,
                ManuscriptRevision.project_id == project.id,
                ManuscriptRevision.user_id == project.user_id,
            )
        )
    ).scalar_one_or_none()
    if not revision or not revision.canonical_snapshot:
        raise CommandError("The active revision has no canonical import snapshot.")
    snapshot = ThesisDocument.model_validate(revision.canonical_snapshot)
    wanted = UUID(str(block_id))
    for entry in snapshot.front_matter:
        for block in entry.body_blocks:
            if block.id == wanted:
                return block.model_dump(mode="json")
    for chapter in snapshot.chapters:
        for block in chapter.blocks:
            if block.id == wanted:
                return block.model_dump(mode="json")
    raise CommandError("This block did not exist in the imported manuscript.")


async def _invalidate_dependencies(
    db: AsyncSession,
    project: Project,
    result: CommandResult,
    user_id: UUID,
) -> None:
    block_ids = {
        UUID(value) for value in result.invalidations.get("citation_block_ids", []) if value
    }
    if block_ids:
        await db.execute(
            delete(CitationResolution).where(
                CitationResolution.project_id == project.id,
                CitationResolution.block_id.in_(block_ids),
            )
        )
    quote_ids = {UUID(value) for value in result.invalidations.get("quote_ids", []) if value}
    if quote_ids:
        quotes = list(
            (
                await db.execute(
                    select(Quote).where(
                        Quote.project_id == project.id,
                        Quote.user_id == user_id,
                        Quote.id.in_(quote_ids),
                    )
                )
            ).scalars()
        )
        for quote in quotes:
            quote.verified = False
            quote.verified_at = None
            quote.verified_by = None
            quote.verification_method = None
    # Existing review items remain as audit records but become superseded until
    # the deterministic verifier synchronises the new document version.
    if block_ids:
        items = list(
            (
                await db.execute(
                    select(ReviewItem).where(
                        ReviewItem.project_id == project.id,
                        ReviewItem.block_id.in_(block_ids),
                        ReviewItem.status.in_(("open", "acknowledged")),
                    )
                )
            ).scalars()
        )
        for item in items:
            item.status = "superseded"
            item.updated_at = datetime.now(timezone.utc)


async def _record_command(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    *,
    command_type: str,
    payload: dict,
    result: CommandResult,
    version_before: int,
    client_request_id: str | None,
    batch_id: UUID | None,
    replays_command_id: UUID | None,
    summary_override: str | None,
) -> DocumentCommand:
    command = DocumentCommand(
        project_id=project.id,
        user_id=user_id,
        command_type=command_type,
        payload=payload,
        inverse_payload=result.inverse_command,
        summary=(summary_override or result.summary)[:400],
        target_type=result.target_type,
        target_id=result.target_id,
        batch_id=batch_id,
        client_request_id=client_request_id,
        document_version_before=version_before,
        document_version_after=project.document_version,
        replays_command_id=replays_command_id,
    )
    db.add(command)
    db.add(
        Event(
            project_id=project.id,
            user_id=user_id,
            kind="document_command_applied",
            data={
                "command_type": command_type,
                "summary": command.summary,
                "version_before": version_before,
                "version_after": project.document_version,
                "target_type": result.target_type,
                "target_id": str(result.target_id) if result.target_id else None,
                "replays_command_id": str(replays_command_id) if replays_command_id else None,
            },
        )
    )
    await db.flush()
    return command


async def _apply(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    *,
    command_type: str,
    payload: dict,
    expected_version: int,
    client_request_id: str | None = None,
    batch_id: UUID | None = None,
    replays_command_id: UUID | None = None,
    summary_override: str | None = None,
    allow_internal: bool = False,
) -> tuple[DocumentCommand, CommandResult]:
    if project.document_version != expected_version:
        raise VersionConflict(expected_version, project.document_version)

    if client_request_id:
        existing = (
            await db.execute(
                select(DocumentCommand).where(
                    DocumentCommand.project_id == project.id,
                    DocumentCommand.client_request_id == client_request_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return existing, CommandResult(
                _document(project),
                existing.inverse_payload,
                existing.summary,
                existing.target_type,
                existing.target_id,
            )

    await _ensure_initial_snapshot(db, project, user_id)
    document = _document(project)
    prepared = dict(payload or {})
    if command_type == "restore_block_original":
        prepared["original_block"] = await _original_block(
            project, db, str(prepared["block_id"])
        )

    version_before = project.document_version
    result = apply_command(document, command_type, prepared, allow_internal=allow_internal)
    await _invalidate_dependencies(db, project, result, user_id)
    apply_payload(project, result.document.model_dump(mode="json"))
    project.document_version = version_before + 1
    command = await _record_command(
        db,
        project,
        user_id,
        command_type=command_type,
        payload=prepared,
        result=result,
        version_before=version_before,
        client_request_id=client_request_id,
        batch_id=batch_id,
        replays_command_id=replays_command_id,
        summary_override=summary_override,
    )
    await _maybe_periodic_snapshot(db, project, user_id)
    await db.commit()
    await db.refresh(project)
    await db.refresh(command)
    return command, result


async def apply_project_command(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    *,
    command_type: str,
    payload: dict,
    expected_version: int,
    client_request_id: str | None = None,
    batch_id: UUID | None = None,
    summary: str | None = None,
) -> tuple[DocumentCommand, CommandResult]:
    return await _apply(
        db,
        project,
        user_id,
        command_type=command_type,
        payload=payload,
        expected_version=expected_version,
        client_request_id=client_request_id,
        batch_id=batch_id,
        summary_override=summary,
    )


async def undo_command(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    target_id: UUID,
    expected_version: int,
) -> tuple[DocumentCommand, CommandResult]:
    target = (
        await db.execute(
            select(DocumentCommand).where(
                DocumentCommand.id == target_id,
                DocumentCommand.project_id == project.id,
                DocumentCommand.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise CommandError("Command not found.")
    if project.document_version != target.document_version_after:
        raise UndoConflict(
            "Only the latest command can be undone safely. Restore a snapshot for older history."
        )
    inverse = target.inverse_payload
    return await _apply(
        db,
        project,
        user_id,
        command_type=inverse["command_type"],
        payload=inverse.get("payload", {}),
        expected_version=expected_version,
        replays_command_id=target.id,
        summary_override=f"Undo: {target.summary}",
        allow_internal=True,
    )


async def redo_command(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    undo_id: UUID,
    expected_version: int,
) -> tuple[DocumentCommand, CommandResult]:
    undo = (
        await db.execute(
            select(DocumentCommand).where(
                DocumentCommand.id == undo_id,
                DocumentCommand.project_id == project.id,
                DocumentCommand.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if undo is None or not undo.summary.startswith("Undo:"):
        raise CommandError("Redo requires an undo command.")
    if project.document_version != undo.document_version_after:
        raise UndoConflict("Redo is available only immediately after its undo.")
    inverse = undo.inverse_payload
    return await _apply(
        db,
        project,
        user_id,
        command_type=inverse["command_type"],
        payload=inverse.get("payload", {}),
        expected_version=expected_version,
        replays_command_id=undo.id,
        summary_override=undo.summary.replace("Undo:", "Redo:", 1),
        allow_internal=True,
    )


async def restore_snapshot(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    snapshot_id: UUID,
    expected_version: int,
) -> tuple[DocumentCommand, CommandResult]:
    snapshot = (
        await db.execute(
            select(DocumentSnapshot).where(
                DocumentSnapshot.id == snapshot_id,
                DocumentSnapshot.project_id == project.id,
                DocumentSnapshot.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise CommandError("Snapshot not found.")
    await create_snapshot(
        db,
        project,
        user_id,
        name=f"Before restoring {snapshot.name}",
        reason="before_restore",
        automatic=True,
    )
    return await _apply(
        db,
        project,
        user_id,
        command_type="restore_document",
        payload={"document": snapshot.canonical_document},
        expected_version=expected_version,
        replays_command_id=None,
        summary_override=f"Restore snapshot: {snapshot.name}",
        allow_internal=True,
    )


def compare_documents(left: dict, right: dict) -> dict:
    """Return a structural comparison without pretending to be a prose diff."""

    a = ThesisDocument.model_validate(left)
    b = ThesisDocument.model_validate(right)
    a_chapters = {chapter.id: chapter for chapter in a.chapters}
    b_chapters = {chapter.id: chapter for chapter in b.chapters}
    added = [str(value) for value in b_chapters.keys() - a_chapters.keys()]
    removed = [str(value) for value in a_chapters.keys() - b_chapters.keys()]
    changed: list[dict] = []
    for chapter_id in a_chapters.keys() & b_chapters.keys():
        before = a_chapters[chapter_id]
        after = b_chapters[chapter_id]
        before_blocks = {block.id: block.model_dump(mode="json") for block in before.blocks}
        after_blocks = {block.id: block.model_dump(mode="json") for block in after.blocks}
        modified = [
            str(block_id)
            for block_id in before_blocks.keys() & after_blocks.keys()
            if before_blocks[block_id] != after_blocks[block_id]
        ]
        inserted = [str(value) for value in after_blocks.keys() - before_blocks.keys()]
        deleted = [str(value) for value in before_blocks.keys() - after_blocks.keys()]
        if before.title != after.title or before.number != after.number or modified or inserted or deleted:
            changed.append(
                {
                    "chapter_id": str(chapter_id),
                    "title_before": before.title,
                    "title_after": after.title,
                    "number_before": before.number,
                    "number_after": after.number,
                    "modified_block_ids": modified,
                    "inserted_block_ids": inserted,
                    "deleted_block_ids": deleted,
                }
            )
    return {
        "chapters_added": added,
        "chapters_removed": removed,
        "chapters_changed": changed,
        "metadata_changed": a.meta.model_dump(mode="json") != b.meta.model_dump(mode="json"),
        "front_matter_changed": a.front_matter != b.front_matter,
        "works_cited_changed": a.works_cited != b.works_cited,
    }
