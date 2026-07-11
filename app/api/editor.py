"""Phase 2 structured editor, history, comparison and search API."""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.canonical.migrations import project_payload
from app.canonical.model import (
    BlockQuoteBlock,
    HeadingBlock,
    MarkerBlock,
    ParagraphBlock,
    ThesisDocument,
    VerseQuoteBlock,
)
from app.db.deps import get_db
from app.editor.commands import CommandError
from app.models.citation_resolution import CitationResolution
from app.models.document_command import DocumentCommand
from app.models.document_snapshot import DocumentSnapshot
from app.models.export import Export
from app.models.manuscript_revision import ManuscriptRevision
from app.models.quote import Quote
from app.models.review_item import ReviewItem
from app.models.source import Source
from app.renderers.phase1_profiles import resolve_phase1_profile
from app.schemas.editor import (
    CommandRecord,
    CommandRequest,
    CommandResultResponse,
    SearchResponse,
    SearchResult,
    SnapshotCreateRequest,
    SnapshotResponse,
    SnapshotRestoreRequest,
    UndoRedoRequest,
)
from app.services.editor_service import (
    UndoConflict,
    VersionConflict,
    apply_project_command,
    compare_documents,
    create_snapshot,
    redo_command,
    restore_snapshot,
    undo_command,
)
from app.services.review_service import sync_review_items


router = APIRouter(tags=["phase2-editor"])


def _command_response(command, result, document_version: int) -> CommandResultResponse:
    return CommandResultResponse(
        command=CommandRecord.model_validate(command),
        document_version=document_version,
        changed_block_ids=sorted(result.changed_block_ids, key=str),
        changed_chapter_ids=sorted(result.changed_chapter_ids, key=str),
        invalidations=result.invalidations,
    )


def _raise_editor_error(exc: Exception) -> None:
    if isinstance(exc, VersionConflict):
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "expected_version": exc.expected,
                "current_version": exc.current,
            },
        ) from None
    if isinstance(exc, UndoConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if isinstance(exc, CommandError):
        raise HTTPException(status_code=422, detail=str(exc)) from None
    raise exc


def _block_text(block) -> str:
    if isinstance(block, ParagraphBlock):
        return "".join(run.text for run in block.runs)
    if isinstance(block, HeadingBlock):
        return block.text
    if isinstance(block, BlockQuoteBlock):
        return block.text
    if isinstance(block, VerseQuoteBlock):
        return "\n".join(block.lines)
    if isinstance(block, MarkerBlock):
        return block.note
    return ""


def _find_block(document: ThesisDocument, block_id: UUID):
    for entry in document.front_matter:
        for index, block in enumerate(entry.body_blocks):
            if block.id == block_id:
                return {"kind": "front_matter", "entry": entry, "index": index, "block": block}
    for chapter in document.chapters:
        for index, block in enumerate(chapter.blocks):
            if block.id == block_id:
                return {"kind": "chapter", "chapter": chapter, "index": index, "block": block}
    return None


def _heading_nodes(chapter) -> list[dict]:
    return [
        {
            "id": str(block.id),
            "level": block.level,
            "text": block.text,
            "source_paragraph_index": block.source_paragraph_index,
        }
        for block in chapter.blocks
        if isinstance(block, HeadingBlock)
    ]


@router.get("/projects/{project_id}/editor/structure")
async def editor_structure(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    document = ThesisDocument.model_validate(project_payload(project))
    ready_exports = list(
        (
            await db.execute(
                select(Export).where(
                    Export.project_id == project.id,
                    Export.user_id == current_user.id,
                    Export.status == "ready",
                )
            )
        ).scalars()
    )
    return {
        "project": {
            "id": str(project.id),
            "title": project.title,
            "document_version": project.document_version,
            "canonical_schema_version": project.canonical_schema_version,
            "format_profile": project.format_profile,
            "active_revision_id": str(project.active_revision_id) if project.active_revision_id else None,
        },
        "front_matter": [
            {
                "id": str(entry.id),
                "kind": entry.kind,
                "status": entry.status,
                "block_count": len(entry.body_blocks),
                "source_paragraph_index": entry.source_paragraph_index,
            }
            for entry in document.front_matter
        ],
        "chapters": [
            {
                "id": str(chapter.id),
                "number": chapter.number,
                "title": chapter.title,
                "status": chapter.status,
                "block_count": len(chapter.blocks),
                "headings": _heading_nodes(chapter),
                "source_paragraph_index": chapter.source_paragraph_index,
            }
            for chapter in document.chapters
        ],
        "works_cited_count": len(document.works_cited),
        "exports": [
            {
                "id": str(row.id),
                "format": row.format,
                "document_version": row.document_version,
                "status": row.status,
                "stale": row.document_version != project.document_version,
                "manifest_state": (row.manifest or {}).get("state"),
                "created_at": row.created_at.isoformat(),
            }
            for row in ready_exports
        ],
    }


@router.get("/projects/{project_id}/editor/chapters/{chapter_id}")
async def get_editor_chapter(
    project_id: UUID,
    chapter_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    document = ThesisDocument.model_validate(project_payload(project))
    chapter = next((value for value in document.chapters if value.id == chapter_id), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return {
        "document_version": project.document_version,
        "chapter": chapter.model_dump(mode="json"),
    }


@router.get("/projects/{project_id}/editor/front-matter/{entry_id}")
async def get_editor_front_matter(
    project_id: UUID,
    entry_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    document = ThesisDocument.model_validate(project_payload(project))
    entry = next((value for value in document.front_matter if value.id == entry_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Front-matter section not found")
    return {"document_version": project.document_version, "entry": entry.model_dump(mode="json")}


@router.get("/projects/{project_id}/editor/blocks/{block_id}/context")
async def block_context(
    project_id: UUID,
    block_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    document = ThesisDocument.model_validate(project_payload(project))
    current = _find_block(document, block_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Block not found")

    original = None
    if project.active_revision_id:
        revision = (
            await db.execute(
                select(ManuscriptRevision).where(
                    ManuscriptRevision.id == project.active_revision_id,
                    ManuscriptRevision.project_id == project.id,
                    ManuscriptRevision.user_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if revision and revision.canonical_snapshot:
            original_doc = ThesisDocument.model_validate(revision.canonical_snapshot)
            original_location = _find_block(original_doc, block_id)
            original = (
                original_location["block"].model_dump(mode="json")
                if original_location
                else None
            )

    commands = list(
        (
            await db.execute(
                select(DocumentCommand)
                .where(
                    DocumentCommand.project_id == project.id,
                    DocumentCommand.target_id == block_id,
                )
                .order_by(DocumentCommand.created_at.desc())
                .limit(30)
            )
        ).scalars()
    )
    items = list(
        (
            await db.execute(
                select(ReviewItem)
                .where(ReviewItem.project_id == project.id, ReviewItem.block_id == block_id)
                .order_by(ReviewItem.created_at.desc())
            )
        ).scalars()
    )
    resolutions = list(
        (
            await db.execute(
                select(CitationResolution).where(
                    CitationResolution.project_id == project.id,
                    CitationResolution.block_id == block_id,
                )
            )
        ).scalars()
    )
    source_ids = {row.source_id for row in resolutions}
    block = current["block"]
    quote_id = getattr(block, "quote_id", None)
    quote = None
    if quote_id:
        quote = (
            await db.execute(
                select(Quote).where(
                    Quote.id == quote_id,
                    Quote.project_id == project.id,
                    Quote.user_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if quote:
            source_ids.add(quote.source_id)
    sources = []
    if source_ids:
        sources = list(
            (
                await db.execute(
                    select(Source).where(
                        Source.project_id == project.id,
                        Source.user_id == current_user.id,
                        Source.id.in_(source_ids),
                    )
                )
            ).scalars()
        )

    return {
        "document_version": project.document_version,
        "location": {
            "kind": current["kind"],
            "chapter_id": str(current["chapter"].id) if current.get("chapter") else None,
            "chapter_number": current["chapter"].number if current.get("chapter") else None,
            "front_matter_id": str(current["entry"].id) if current.get("entry") else None,
            "index": current["index"],
        },
        "current": block.model_dump(mode="json"),
        "original": original,
        "changed": original is not None and original != block.model_dump(mode="json"),
        "commands": [CommandRecord.model_validate(row).model_dump(mode="json") for row in commands],
        "review_items": [
            {
                "id": str(item.id),
                "rule": item.rule,
                "severity": item.severity,
                "title": item.title,
                "status": item.status,
            }
            for item in items
        ],
        "citation_resolutions": [
            {"raw_citation": row.raw_citation, "source_id": str(row.source_id)}
            for row in resolutions
        ],
        "sources": [
            {
                "id": str(source.id),
                "kind": source.kind,
                "fields": source.fields,
                "verified": source.verified,
                "raw_entry": source.raw_entry,
            }
            for source in sources
        ],
        "quote": (
            {
                "id": str(quote.id),
                "source_id": str(quote.source_id),
                "text": quote.text,
                "page_or_loc": quote.page_or_loc,
                "verified": quote.verified,
            }
            if quote
            else None
        ),
    }


@router.post(
    "/projects/{project_id}/editor/commands",
    response_model=CommandResultResponse,
)
async def apply_editor_command(
    project_id: UUID,
    body: CommandRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CommandResultResponse:
    project = await fetch_owned_project(db, project_id, current_user.id)

    if body.command_type == "set_chapter_status" and body.payload.get("status") == "locked":
        rows, _report, _readiness = await sync_review_items(db, project)
        chapter_id = str(body.payload.get("chapter_id"))
        blocking = [
            item
            for item in rows
            if item.status == "open"
            and item.severity == "block"
            and str((item.location or {}).get("chapter_id")) == chapter_id
        ]
        if blocking:
            raise HTTPException(
                status_code=409,
                detail="Chapter cannot be locked while blocking review items remain.",
            )

    if body.command_type == "reorder_front_matter":
        document = ThesisDocument.model_validate(project_payload(project))
        profile, _version = resolve_phase1_profile(project.format_profile)
        by_id = {str(entry.id): entry.kind for entry in document.front_matter}
        kinds = [by_id.get(str(value)) for value in body.payload.get("entry_ids", [])]
        governed = [kind for kind in profile.front_matter_order if kind in kinds]
        if [kind for kind in kinds if kind in profile.front_matter_order] != governed:
            raise HTTPException(
                status_code=409,
                detail="Front-matter order conflicts with the governed institution profile.",
            )

    try:
        command, result = await apply_project_command(
            db,
            project,
            current_user.id,
            command_type=body.command_type,
            payload=body.payload,
            expected_version=body.expected_document_version,
            client_request_id=body.client_request_id,
            batch_id=body.batch_id,
            summary=body.summary,
        )
    except Exception as exc:
        _raise_editor_error(exc)
    return _command_response(command, result, project.document_version)


@router.get("/projects/{project_id}/editor/commands", response_model=list[CommandRecord])
async def list_editor_commands(
    project_id: UUID,
    current_user: CurrentUser,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    await fetch_owned_project(db, project_id, current_user.id)
    return list(
        (
            await db.execute(
                select(DocumentCommand)
                .where(
                    DocumentCommand.project_id == project_id,
                    DocumentCommand.user_id == current_user.id,
                )
                .order_by(DocumentCommand.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )


@router.post(
    "/projects/{project_id}/editor/commands/{command_id}/undo",
    response_model=CommandResultResponse,
)
async def undo_editor_command(
    project_id: UUID,
    command_id: UUID,
    body: UndoRedoRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    try:
        command, result = await undo_command(
            db, project, current_user.id, command_id, body.expected_document_version
        )
    except Exception as exc:
        _raise_editor_error(exc)
    return _command_response(command, result, project.document_version)


@router.post(
    "/projects/{project_id}/editor/commands/{command_id}/redo",
    response_model=CommandResultResponse,
)
async def redo_editor_command(
    project_id: UUID,
    command_id: UUID,
    body: UndoRedoRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    try:
        command, result = await redo_command(
            db, project, current_user.id, command_id, body.expected_document_version
        )
    except Exception as exc:
        _raise_editor_error(exc)
    return _command_response(command, result, project.document_version)


@router.post("/projects/{project_id}/editor/snapshots", response_model=SnapshotResponse)
async def create_editor_snapshot(
    project_id: UUID,
    body: SnapshotCreateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    if project.document_version != body.expected_document_version:
        raise HTTPException(status_code=409, detail="Project changed before checkpoint creation.")
    row = await create_snapshot(
        db,
        project,
        current_user.id,
        name=body.name,
        reason="manual",
        automatic=False,
    )
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/projects/{project_id}/editor/snapshots", response_model=list[SnapshotResponse])
async def list_editor_snapshots(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await fetch_owned_project(db, project_id, current_user.id)
    return list(
        (
            await db.execute(
                select(DocumentSnapshot)
                .where(
                    DocumentSnapshot.project_id == project_id,
                    DocumentSnapshot.user_id == current_user.id,
                )
                .order_by(DocumentSnapshot.created_at.desc())
                .limit(200)
            )
        ).scalars()
    )


@router.post(
    "/projects/{project_id}/editor/snapshots/{snapshot_id}/restore",
    response_model=CommandResultResponse,
)
async def restore_editor_snapshot(
    project_id: UUID,
    snapshot_id: UUID,
    body: SnapshotRestoreRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    try:
        command, result = await restore_snapshot(
            db,
            project,
            current_user.id,
            snapshot_id,
            body.expected_document_version,
        )
    except Exception as exc:
        _raise_editor_error(exc)
    return _command_response(command, result, project.document_version)


@router.get("/projects/{project_id}/editor/snapshots/{snapshot_id}/compare")
async def compare_editor_snapshot(
    project_id: UUID,
    snapshot_id: UUID,
    current_user: CurrentUser,
    other_snapshot_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    left = (
        await db.execute(
            select(DocumentSnapshot).where(
                DocumentSnapshot.id == snapshot_id,
                DocumentSnapshot.project_id == project.id,
                DocumentSnapshot.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if left is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    right_payload = project_payload(project)
    right_label = f"Current v{project.document_version}"
    if other_snapshot_id:
        right = (
            await db.execute(
                select(DocumentSnapshot).where(
                    DocumentSnapshot.id == other_snapshot_id,
                    DocumentSnapshot.project_id == project.id,
                    DocumentSnapshot.user_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if right is None:
            raise HTTPException(status_code=404, detail="Comparison snapshot not found")
        right_payload = right.canonical_document
        right_label = right.name
    return {
        "left": {"id": str(left.id), "label": left.name, "version": left.document_version},
        "right": {"id": str(other_snapshot_id) if other_snapshot_id else None, "label": right_label},
        "comparison": compare_documents(left.canonical_document, right_payload),
    }


def _parse_search_query(query: str) -> tuple[str, dict[str, str]]:
    filters: dict[str, str] = {}
    pattern = re.compile(r"\b(type|chapter|marker|status):(?:\"([^\"]+)\"|(\S+))", re.I)
    for match in pattern.finditer(query):
        filters[match.group(1).lower()] = (match.group(2) or match.group(3)).strip()
    text = pattern.sub("", query).strip().strip('"')
    return text, filters


@router.get("/projects/{project_id}/editor/search", response_model=SearchResponse)
async def search_editor_document(
    project_id: UUID,
    q: str = Query(..., min_length=1, max_length=300),
    current_user: CurrentUser = None,
    limit: int = Query(100, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    document = ThesisDocument.model_validate(project_payload(project))
    text, filters = _parse_search_query(q)
    needle = text.casefold()
    results: list[SearchResult] = []

    for chapter in document.chapters:
        if filters.get("chapter") and filters["chapter"].casefold() not in {
            str(chapter.number).casefold(), chapter.title.casefold(), str(chapter.id).casefold()
        }:
            continue
        if filters.get("status") and chapter.status != filters["status"]:
            continue
        if not needle or needle in chapter.title.casefold():
            results.append(
                SearchResult(
                    kind="chapter",
                    id=chapter.id,
                    chapter_id=chapter.id,
                    chapter_number=chapter.number,
                    status=chapter.status,
                    title=chapter.title,
                    snippet=f"Chapter {chapter.number}: {chapter.title}",
                    source_paragraph_index=chapter.source_paragraph_index,
                )
            )
        for block in chapter.blocks:
            if filters.get("type") and block.type != filters["type"]:
                continue
            if filters.get("marker"):
                if not isinstance(block, MarkerBlock) or block.kind != filters["marker"]:
                    continue
            content = _block_text(block)
            if needle and needle not in content.casefold():
                continue
            results.append(
                SearchResult(
                    kind="block",
                    id=block.id,
                    chapter_id=chapter.id,
                    chapter_number=chapter.number,
                    block_type=block.type,
                    status=chapter.status,
                    title=content[:80],
                    snippet=content[:300],
                    source_paragraph_index=block.source_paragraph_index,
                )
            )
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    return SearchResponse(query=q, total=len(results), results=results[:limit])
