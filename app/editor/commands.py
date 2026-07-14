"""Pure command engine for the structured thesis editor.

The engine never touches the database. It accepts a validated ThesisDocument,
returns a new validated document, and emits a server-generated inverse command.
This makes undo deterministic and lets tests prove apply → inverse == original.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from pydantic import TypeAdapter

from app.canonical.model import (
    Block,
    BlockQuoteBlock,
    ChapterDoc,
    FrontMatterEntry,
    HeadingBlock,
    MarkerBlock,
    ParagraphBlock,
    Run,
    ThesisDocument,
    VerseQuoteBlock,
)


_BLOCK_ADAPTER = TypeAdapter(Block)
_ALLOWED_REVIEW_STATES = {
    "imported",
    "needs_review",
    "in_progress",
    "reviewed",
    "approved",
    "locked",
    "draft",
    "review",
}
_EDITABLE_FRONT_MATTER = {"acknowledgement", "ai_disclosure", "abbreviations"}


class CommandError(ValueError):
    pass


@dataclass
class CommandResult:
    document: ThesisDocument
    inverse_command: dict
    summary: str
    target_type: str | None = None
    target_id: UUID | None = None
    changed_block_ids: set[UUID] = field(default_factory=set)
    changed_chapter_ids: set[UUID] = field(default_factory=set)
    invalidations: dict[str, list[str]] = field(
        default_factory=lambda: {
            "citation_block_ids": [],
            "quote_ids": [],
            "chapter_ids": [],
            "preview": ["document_changed"],
            "exports": ["document_changed"],
        }
    )


def _clone(document: ThesisDocument) -> ThesisDocument:
    return ThesisDocument.model_validate(document.model_dump(mode="json"))


def _chapter(document: ThesisDocument, chapter_id: UUID | str) -> ChapterDoc:
    wanted = UUID(str(chapter_id))
    for chapter in document.chapters:
        if chapter.id == wanted:
            return chapter
    raise CommandError("Chapter not found.")


def _front_entry(document: ThesisDocument, entry_id: UUID | str) -> FrontMatterEntry:
    wanted = UUID(str(entry_id))
    for entry in document.front_matter:
        if entry.id == wanted:
            return entry
    raise CommandError("Front-matter section not found.")


def _find_block(document: ThesisDocument, block_id: UUID | str):
    wanted = UUID(str(block_id))
    for entry in document.front_matter:
        for index, block in enumerate(entry.body_blocks):
            if block.id == wanted:
                return "front_matter", entry, index, block
    for chapter in document.chapters:
        for index, block in enumerate(chapter.blocks):
            if block.id == wanted:
                return "chapter", chapter, index, block
    raise CommandError("Block not found.")


def _container_blocks(container) -> list:
    if isinstance(container, ChapterDoc):
        return container.blocks
    if isinstance(container, FrontMatterEntry):
        return container.body_blocks
    raise CommandError("Unsupported block container.")


def _ensure_editable(container) -> None:
    if isinstance(container, ChapterDoc) and container.status == "locked":
        raise CommandError("This chapter is locked. Unlock it before editing.")
    if isinstance(container, FrontMatterEntry):
        if container.status == "locked":
            raise CommandError("This front-matter section is locked.")
        if container.kind not in _EDITABLE_FRONT_MATTER:
            raise CommandError(
                "Institution-controlled front matter is edited through metadata, not free text."
            )


def _mark_changed(container) -> None:
    if container.status in {"approved", "reviewed", "review", "imported", "draft"}:
        container.status = "needs_review"


def _block_text(block: Block) -> str:
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
    raise CommandError("Unsupported block type.")


def _block_payload(block: Block) -> dict:
    return block.model_dump(mode="json")


def _restore_container_inverse(container) -> dict:
    if isinstance(container, ChapterDoc):
        return {
            "command_type": "restore_chapter_blocks",
            "payload": {
                "chapter_id": str(container.id),
                "blocks": [_block_payload(block) for block in container.blocks],
                "status": container.status,
            },
        }
    return {
        "command_type": "restore_front_matter_blocks",
        "payload": {
            "entry_id": str(container.id),
            "blocks": [_block_payload(block) for block in container.body_blocks],
            "status": container.status,
        },
    }


def _split_runs(runs: list[Run], offset: int) -> tuple[list[Run], list[Run]]:
    if offset < 0 or offset > sum(len(run.text) for run in runs):
        raise CommandError("Split offset is outside the paragraph.")
    left: list[Run] = []
    right: list[Run] = []
    consumed = 0
    for run in runs:
        end = consumed + len(run.text)
        if end <= offset:
            left.append(run.model_copy(deep=True))
        elif consumed >= offset:
            right.append(run.model_copy(deep=True))
        else:
            cut = offset - consumed
            if run.text[:cut]:
                left.append(Run(text=run.text[:cut], italic=run.italic))
            if run.text[cut:]:
                right.append(Run(text=run.text[cut:], italic=run.italic))
        consumed = end
    return left, right


def _preserved_identity(block: Block) -> dict:
    return {
        "id": block.id,
        "source_revision_id": block.source_revision_id,
        "source_paragraph_index": block.source_paragraph_index,
        "origin": block.origin,
    }


def _convert_block(block: Block, target_type: str, payload: dict) -> Block:
    identity = _preserved_identity(block)
    text = _block_text(block)
    if target_type == "paragraph":
        return ParagraphBlock(**identity, runs=[Run(text=text)])
    if target_type == "heading":
        level = int(payload.get("level", 2))
        if level not in (2, 3):
            raise CommandError("Heading level must be 2 or 3.")
        return HeadingBlock(**identity, text=text, level=level)
    if target_type == "block_quote":
        citation = payload.get("citation", getattr(block, "citation", ""))
        quote_id = getattr(block, "quote_id", None)
        return BlockQuoteBlock(**identity, text=text, citation=citation, quote_id=quote_id)
    if target_type == "verse_quote":
        citation = payload.get("citation", getattr(block, "citation", ""))
        quote_id = getattr(block, "quote_id", None)
        return VerseQuoteBlock(
            **identity,
            lines=text.splitlines() or [text],
            citation=citation,
            quote_id=quote_id,
        )
    if target_type == "marker":
        kind = payload.get("kind", "REVIEW_REQUIRED")
        return MarkerBlock(**identity, kind=kind, note=text, evidence=payload.get("evidence", {}))
    raise CommandError(f"Unsupported target block type: {target_type}")


def _metadata_set(meta: dict, path: str, value: Any) -> Any:
    allowed_roots = {
        "title",
        "candidate",
        "degree",
        "department",
        "college",
        "guide",
        "hod",
        "submission",
        "ai_disclosure",
        "doc_type",
    }
    parts = [part for part in path.split(".") if part]
    if not parts or parts[0] not in allowed_roots:
        raise CommandError("Metadata path is not editable.")
    cursor = meta
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    old = deepcopy(cursor.get(parts[-1]))
    cursor[parts[-1]] = value
    return old


def _validate_document(document: ThesisDocument) -> ThesisDocument:
    numbers = [chapter.number for chapter in document.chapters]
    if len(numbers) != len(set(numbers)):
        raise CommandError("Chapter numbers must remain unique.")
    return ThesisDocument.model_validate(document.model_dump(mode="json"))


def apply_command(
    document: ThesisDocument,
    command_type: str,
    payload: dict,
    *,
    allow_internal: bool = False,
) -> CommandResult:
    doc = _clone(document)
    payload = deepcopy(payload or {})
    changed_blocks: set[UUID] = set()
    changed_chapters: set[UUID] = set()
    invalidations = {
        "citation_block_ids": [],
        "quote_ids": [],
        "chapter_ids": [],
        "preview": ["document_changed"],
        "exports": ["document_changed"],
    }

    if command_type == "restore_document":
        if not allow_internal:
            raise CommandError("restore_document is an internal command.")
        restored = ThesisDocument.model_validate(payload["document"])
        inverse = {
            "command_type": "restore_document",
            "payload": {"document": doc.model_dump(mode="json")},
        }
        return CommandResult(restored, inverse, "Restore document state")

    if command_type == "restore_chapter_blocks":
        if not allow_internal:
            raise CommandError("restore_chapter_blocks is an internal command.")
        chapter = _chapter(doc, payload["chapter_id"])
        inverse = _restore_container_inverse(chapter)
        chapter.blocks = [_BLOCK_ADAPTER.validate_python(item) for item in payload["blocks"]]
        chapter.status = payload.get("status", chapter.status)
        changed_chapters.add(chapter.id)
        changed_blocks.update(block.id for block in chapter.blocks)
        return CommandResult(
            _validate_document(doc),
            inverse,
            "Restore chapter blocks",
            "chapter",
            chapter.id,
            changed_blocks,
            changed_chapters,
            invalidations,
        )

    if command_type == "restore_front_matter_blocks":
        if not allow_internal:
            raise CommandError("restore_front_matter_blocks is an internal command.")
        entry = _front_entry(doc, payload["entry_id"])
        inverse = _restore_container_inverse(entry)
        entry.body_blocks = [_BLOCK_ADAPTER.validate_python(item) for item in payload["blocks"]]
        entry.status = payload.get("status", entry.status)
        changed_blocks.update(block.id for block in entry.body_blocks)
        return CommandResult(
            _validate_document(doc),
            inverse,
            "Restore front-matter blocks",
            "front_matter",
            entry.id,
            changed_blocks,
            changed_chapters,
            invalidations,
        )

    if command_type == "batch":
        before = doc.model_dump(mode="json")
        summaries: list[str] = []
        for child in payload.get("commands", []):
            result = apply_command(
                doc,
                child["command_type"],
                child.get("payload", {}),
                allow_internal=False,
            )
            doc = result.document
            summaries.append(result.summary)
            changed_blocks |= result.changed_block_ids
            changed_chapters |= result.changed_chapter_ids
            for key, values in result.invalidations.items():
                invalidations.setdefault(key, []).extend(values)
        inverse = {"command_type": "restore_document", "payload": {"document": before}}
        return CommandResult(
            _validate_document(doc),
            inverse,
            f"Apply {len(summaries)} edits",
            "document",
            None,
            changed_blocks,
            changed_chapters,
            invalidations,
        )

    if command_type == "update_metadata":
        before = doc.meta.model_dump(mode="json")
        path = str(payload.get("path", ""))
        value = payload.get("value")
        updated = deepcopy(before)
        old = _metadata_set(updated, path, value)
        doc.meta = doc.meta.model_validate(updated)
        inverse = {
            "command_type": "update_metadata",
            "payload": {"path": path, "value": old},
        }
        return CommandResult(
            _validate_document(doc),
            inverse,
            f"Update metadata: {path}",
            "metadata",
            None,
            changed_blocks,
            changed_chapters,
            invalidations,
        )

    if command_type == "reorder_chapters":
        wanted = [UUID(str(value)) for value in payload.get("chapter_ids", [])]
        current = [chapter.id for chapter in doc.chapters]
        if len(wanted) != len(current) or set(wanted) != set(current):
            raise CommandError("Chapter reordering must contain each chapter exactly once.")
        before = [str(value) for value in current]
        by_id = {chapter.id: chapter for chapter in doc.chapters}
        doc.chapters = [by_id[value] for value in wanted]
        inverse = {"command_type": "reorder_chapters", "payload": {"chapter_ids": before}}
        return CommandResult(
            _validate_document(doc), inverse, "Reorder chapters", "document", None
        )

    if command_type == "reorder_front_matter":
        wanted = [UUID(str(value)) for value in payload.get("entry_ids", [])]
        current = [entry.id for entry in doc.front_matter]
        if len(wanted) != len(current) or set(wanted) != set(current):
            raise CommandError("Front-matter order must contain each section exactly once.")
        before = [str(value) for value in current]
        by_id = {entry.id: entry for entry in doc.front_matter}
        doc.front_matter = [by_id[value] for value in wanted]
        inverse = {"command_type": "reorder_front_matter", "payload": {"entry_ids": before}}
        return CommandResult(
            _validate_document(doc), inverse, "Reorder front matter", "document", None
        )

    if command_type in {"update_chapter", "set_chapter_status"}:
        chapter = _chapter(doc, payload["chapter_id"])
        before = chapter.model_dump(mode="json")
        if command_type == "set_chapter_status":
            status = payload.get("status")
            if status not in _ALLOWED_REVIEW_STATES:
                raise CommandError("Unsupported chapter review status.")
            chapter.status = status
            summary = f"Set Chapter {chapter.number} status to {status}"
        else:
            if chapter.status == "locked":
                raise CommandError("This chapter is locked. Unlock it before editing.")
            if "title" in payload:
                chapter.title = str(payload["title"]).strip()
                if not chapter.title:
                    raise CommandError("Chapter title cannot be blank.")
            if "number" in payload:
                chapter.number = int(payload["number"])
                if chapter.number < 1:
                    raise CommandError("Chapter number must be positive.")
            _mark_changed(chapter)
            summary = f"Update Chapter {chapter.number}"
        changed_chapters.add(chapter.id)
        invalidations["chapter_ids"].append(str(chapter.id))
        inverse = {
            "command_type": "restore_chapter",
            "payload": {"chapter": before},
        }
        # restore_chapter is handled below through the internal branch.
        return CommandResult(
            _validate_document(doc),
            inverse,
            summary,
            "chapter",
            chapter.id,
            changed_blocks,
            changed_chapters,
            invalidations,
        )

    if command_type == "restore_chapter":
        if not allow_internal:
            raise CommandError("restore_chapter is an internal command.")
        restored = ChapterDoc.model_validate(payload["chapter"])
        current = _chapter(doc, restored.id)
        inverse = {"command_type": "restore_chapter", "payload": {"chapter": current.model_dump(mode="json")}}
        index = next(i for i, chapter in enumerate(doc.chapters) if chapter.id == restored.id)
        doc.chapters[index] = restored
        return CommandResult(
            _validate_document(doc), inverse, "Restore chapter", "chapter", restored.id
        )

    if command_type in {"set_front_matter_status", "update_front_matter_body"}:
        entry = _front_entry(doc, payload["entry_id"])
        before = entry.model_dump(mode="json")
        if command_type == "set_front_matter_status":
            status = payload.get("status")
            if status not in _ALLOWED_REVIEW_STATES:
                raise CommandError("Unsupported front-matter review status.")
            entry.status = status
            summary = f"Set {entry.kind} status to {status}"
        else:
            _ensure_editable(entry)
            entry.body_blocks = [
                _BLOCK_ADAPTER.validate_python(block) for block in payload.get("blocks", [])
            ]
            _mark_changed(entry)
            changed_blocks.update(block.id for block in entry.body_blocks)
            summary = f"Update {entry.kind} content"
        inverse = {
            "command_type": "restore_front_matter_entry",
            "payload": {"entry": before},
        }
        return CommandResult(
            _validate_document(doc), inverse, summary, "front_matter", entry.id, changed_blocks
        )

    if command_type == "restore_front_matter_entry":
        if not allow_internal:
            raise CommandError("restore_front_matter_entry is an internal command.")
        restored = FrontMatterEntry.model_validate(payload["entry"])
        current = _front_entry(doc, restored.id)
        inverse = {
            "command_type": "restore_front_matter_entry",
            "payload": {"entry": current.model_dump(mode="json")},
        }
        index = next(i for i, entry in enumerate(doc.front_matter) if entry.id == restored.id)
        doc.front_matter[index] = restored
        return CommandResult(
            _validate_document(doc), inverse, "Restore front matter", "front_matter", restored.id
        )

    # Remaining commands target a block or a chapter container.
    if command_type == "insert_block":
        chapter = _chapter(doc, payload["chapter_id"])
        _ensure_editable(chapter)
        inverse = _restore_container_inverse(chapter)
        block_payload = deepcopy(payload.get("block") or {"type": "paragraph", "runs": [{"text": ""}]})
        block_payload.setdefault("id", str(uuid4()))
        # Editor inserts are human-authored. The AI proposal path passes an
        # explicit ``origin`` in the block dict, so setdefault leaves it intact.
        block_payload.setdefault("origin", "human")
        block = _BLOCK_ADAPTER.validate_python(block_payload)
        if any(existing.id == block.id for existing in chapter.blocks):
            raise CommandError("Block ID already exists in this chapter.")
        index = payload.get("index")
        if index is None and payload.get("after_block_id"):
            after = UUID(str(payload["after_block_id"]))
            index = next((i + 1 for i, item in enumerate(chapter.blocks) if item.id == after), None)
        if index is None:
            index = len(chapter.blocks)
        index = max(0, min(int(index), len(chapter.blocks)))
        chapter.blocks.insert(index, block)
        _mark_changed(chapter)
        changed_blocks.add(block.id)
        changed_chapters.add(chapter.id)
        invalidations["chapter_ids"].append(str(chapter.id))
        return CommandResult(
            _validate_document(doc),
            inverse,
            "Insert block",
            "block",
            block.id,
            changed_blocks,
            changed_chapters,
            invalidations,
        )

    if command_type == "restore_block_original":
        original = payload.get("original_block")
        if not original:
            raise CommandError("Original imported block was not supplied.")
        location, container, index, current = _find_block(doc, payload["block_id"])
        _ensure_editable(container)
        inverse = _restore_container_inverse(container)
        original["id"] = str(current.id)
        original["source_revision_id"] = (
            str(current.source_revision_id) if current.source_revision_id else None
        )
        original["source_paragraph_index"] = current.source_paragraph_index
        replacement = _BLOCK_ADAPTER.validate_python(original)
        _container_blocks(container)[index] = replacement
        _mark_changed(container)
        changed_blocks.add(current.id)
        if isinstance(container, ChapterDoc):
            changed_chapters.add(container.id)
            invalidations["chapter_ids"].append(str(container.id))
        invalidations["citation_block_ids"].append(str(current.id))
        quote_id = getattr(current, "quote_id", None)
        if quote_id:
            invalidations["quote_ids"].append(str(quote_id))
        return CommandResult(
            _validate_document(doc), inverse, "Restore imported block", "block", current.id,
            changed_blocks, changed_chapters, invalidations
        )

    block_id = payload.get("block_id")
    if not block_id:
        raise CommandError("This command requires block_id.")
    location, container, index, block = _find_block(doc, block_id)
    _ensure_editable(container)
    inverse = _restore_container_inverse(container)
    blocks = _container_blocks(container)

    if command_type == "update_block":
        replacement_payload = deepcopy(payload["block"])
        replacement_payload["id"] = str(block.id)
        replacement_payload.setdefault(
            "source_revision_id", str(block.source_revision_id) if block.source_revision_id else None
        )
        replacement_payload.setdefault("source_paragraph_index", block.source_paragraph_index)
        replacement_payload.setdefault("origin", block.origin)
        replacement = _BLOCK_ADAPTER.validate_python(replacement_payload)
        if replacement.type != block.type:
            raise CommandError("Use change_block_type for structural conversion.")
        blocks[index] = replacement
        summary = f"Update {block.type.replace('_', ' ')}"
    elif command_type == "update_block_text":
        if isinstance(block, ParagraphBlock):
            runs = payload.get("runs")
            block.runs = (
                [Run.model_validate(run) for run in runs]
                if runs is not None
                else [Run(text=str(payload.get("text", "")))]
            )
        elif isinstance(block, HeadingBlock):
            block.text = str(payload.get("text", block.text))
            if "level" in payload:
                level = int(payload["level"])
                if level not in (2, 3):
                    raise CommandError("Heading level must be 2 or 3.")
                block.level = level
        elif isinstance(block, BlockQuoteBlock):
            block.text = str(payload.get("text", block.text))
            if "citation" in payload:
                block.citation = str(payload["citation"])
        elif isinstance(block, VerseQuoteBlock):
            if "lines" in payload:
                block.lines = [str(line) for line in payload["lines"]]
            elif "text" in payload:
                block.lines = str(payload["text"]).splitlines()
            if "citation" in payload:
                block.citation = str(payload["citation"])
        elif isinstance(block, MarkerBlock):
            block.note = str(payload.get("text", payload.get("note", block.note)))
            if "kind" in payload:
                block.kind = payload["kind"]
        summary = f"Edit {block.type.replace('_', ' ')}"
    elif command_type == "change_block_type":
        blocks[index] = _convert_block(block, str(payload["target_type"]), payload)
        summary = f"Convert block to {payload['target_type']}"
    elif command_type == "delete_block":
        blocks.pop(index)
        summary = "Delete block"
    elif command_type == "duplicate_block":
        duplicate = deepcopy(_block_payload(block))
        duplicate["id"] = str(uuid4())
        duplicate["source_revision_id"] = None
        duplicate["source_paragraph_index"] = None
        duplicated = _BLOCK_ADAPTER.validate_python(duplicate)
        blocks.insert(index + 1, duplicated)
        changed_blocks.add(duplicated.id)
        summary = "Duplicate block"
    elif command_type == "move_block":
        if not isinstance(container, ChapterDoc):
            raise CommandError("Front-matter blocks cannot be moved between chapters.")
        target = _chapter(doc, payload["to_chapter_id"])
        _ensure_editable(target)
        moving = blocks.pop(index)
        target_index = max(0, min(int(payload.get("to_index", len(target.blocks))), len(target.blocks)))
        target.blocks.insert(target_index, moving)
        _mark_changed(target)
        changed_chapters.add(target.id)
        invalidations["chapter_ids"].append(str(target.id))
        summary = f"Move block to Chapter {target.number}"
    elif command_type == "split_block":
        if not isinstance(block, ParagraphBlock):
            raise CommandError("Only paragraph blocks can be split safely.")
        left, right = _split_runs(block.runs, int(payload["offset"]))
        if not left or not right:
            raise CommandError("Split must leave text on both sides.")
        block.runs = left
        # The split-off paragraph shares the authorship of the paragraph it came
        # from; a split is a human editing action, not new authorship.
        new_block = ParagraphBlock(runs=right, origin=block.origin)
        blocks.insert(index + 1, new_block)
        changed_blocks.add(new_block.id)
        summary = "Split paragraph"
    elif command_type == "merge_blocks":
        if not isinstance(block, ParagraphBlock):
            raise CommandError("Only paragraph blocks can be merged safely.")
        other_id = UUID(str(payload["other_block_id"]))
        other_index = next((i for i, candidate in enumerate(blocks) if candidate.id == other_id), None)
        if other_index is None or abs(other_index - index) != 1:
            raise CommandError("Paragraphs must be adjacent to merge.")
        first_index, second_index = sorted((index, other_index))
        first = blocks[first_index]
        second = blocks[second_index]
        if not isinstance(first, ParagraphBlock) or not isinstance(second, ParagraphBlock):
            raise CommandError("Only paragraph blocks can be merged.")
        separator = str(payload.get("separator", " "))
        if separator:
            first.runs.append(Run(text=separator))
        first.runs.extend(run.model_copy(deep=True) for run in second.runs)
        removed = blocks.pop(second_index)
        changed_blocks.add(removed.id)
        block = first
        summary = "Merge paragraphs"
    elif command_type == "add_marker":
        marker = MarkerBlock(
            kind=payload.get("kind", "REVIEW_REQUIRED"),
            note=str(payload.get("note", "Review required")),
            evidence=payload.get("evidence", {}),
            origin=payload.get("origin"),
        )
        blocks.insert(index + 1, marker)
        changed_blocks.add(marker.id)
        summary = f"Add {marker.kind} marker"
    else:
        raise CommandError(f"Unsupported command type: {command_type}")

    _mark_changed(container)
    changed_blocks.add(block.id)
    invalidations["citation_block_ids"].append(str(block.id))
    quote_id = getattr(block, "quote_id", None)
    if quote_id:
        invalidations["quote_ids"].append(str(quote_id))
    if isinstance(container, ChapterDoc):
        changed_chapters.add(container.id)
        invalidations["chapter_ids"].append(str(container.id))

    target_id = block.id
    if command_type == "duplicate_block":
        target_id = blocks[index + 1].id
    return CommandResult(
        _validate_document(doc),
        inverse,
        summary,
        "block",
        target_id,
        changed_blocks,
        changed_chapters,
        invalidations,
    )
