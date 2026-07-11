"""Fast invariants for the Phase 2 structured editor and review contracts."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.canonical.migrations import upgrade_canonical_payload
from app.canonical.model import ThesisDocument
from app.editor.commands import CommandError, apply_command
from app.services.review_service import _fingerprint


def _document() -> ThesisDocument:
    return ThesisDocument.model_validate(
        {
            "meta": {
                "title": "Memory and Identity",
                "candidate": {"name": "Febin", "reg_no": "AC001"},
            },
            "front_matter": [
                {"kind": "title_page"},
                {
                    "kind": "acknowledgement",
                    "body_blocks": [
                        {"type": "paragraph", "runs": [{"text": "Thank you."}]}
                    ],
                },
                {"kind": "contents"},
            ],
            "chapters": [
                {
                    "number": 1,
                    "title": "Introduction",
                    "status": "in_progress",
                    "blocks": [
                        {
                            "type": "paragraph",
                            "runs": [
                                {"text": "Achebe’s "},
                                {"text": "Things Fall Apart", "italic": True},
                                {"text": " challenges colonial narration."},
                            ],
                        },
                        {"type": "heading", "level": 2, "text": "Background"},
                    ],
                },
                {
                    "number": 2,
                    "title": "Analysis",
                    "status": "imported",
                    "blocks": [
                        {"type": "paragraph", "runs": [{"text": "Analysis begins."}]}
                    ],
                },
            ],
        }
    )


def _roundtrip(document: ThesisDocument, command_type: str, payload: dict) -> None:
    original = document.model_dump(mode="json")
    applied = apply_command(document, command_type, payload)
    inverse = applied.inverse_command
    restored = apply_command(
        applied.document,
        inverse["command_type"],
        inverse.get("payload", {}),
        allow_internal=True,
    )
    assert restored.document.model_dump(mode="json") == original


def test_canonical_v2_migrates_to_v3_without_losing_ids() -> None:
    block_id = uuid4()
    legacy = {
        "schema_version": 2,
        "meta": {"title": "Legacy"},
        "front_matter": [{"kind": "title_page"}],
        "chapters": [
            {
                "number": 1,
                "title": "Intro",
                "status": "draft",
                "blocks": [
                    {
                        "id": str(block_id),
                        "type": "paragraph",
                        "runs": [{"text": "Preserved"}],
                    }
                ],
            }
        ],
    }
    upgraded = upgrade_canonical_payload(legacy, 2)
    assert upgraded["schema_version"] == 3
    assert upgraded["chapters"][0]["status"] == "in_progress"
    assert upgraded["chapters"][0]["blocks"][0]["id"] == str(block_id)
    assert upgraded["front_matter"][0]["status"] == "imported"
    assert upgraded["meta"]["ai_disclosure"]["tools"] == []


def test_update_text_is_exactly_reversible_and_preserves_block_id() -> None:
    document = _document()
    block = document.chapters[0].blocks[0]
    applied = apply_command(
        document,
        "update_block_text",
        {
            "block_id": str(block.id),
            "runs": [{"text": "Revised meaning", "italic": False}],
        },
    )
    assert applied.document.chapters[0].blocks[0].id == block.id
    # A chapter already being actively edited remains in progress.
    assert applied.document.chapters[0].status == "in_progress"
    inverse = applied.inverse_command
    restored = apply_command(
        applied.document,
        inverse["command_type"],
        inverse["payload"],
        allow_internal=True,
    )
    assert restored.document.model_dump(mode="json") == document.model_dump(mode="json")


def test_editing_approved_content_invalidates_approval() -> None:
    document = _document()
    document.chapters[0].status = "approved"
    block = document.chapters[0].blocks[0]
    result = apply_command(
        document,
        "update_block_text",
        {"block_id": str(block.id), "text": "Approval-invalidating correction."},
    )
    assert result.document.chapters[0].status == "needs_review"
    assert str(document.chapters[0].id) in result.invalidations["chapter_ids"]


def test_split_and_insert_commands_roundtrip() -> None:
    document = _document()
    block = document.chapters[0].blocks[0]
    text = "".join(run.text for run in block.runs)
    _roundtrip(
        document,
        "split_block",
        {"block_id": str(block.id), "offset": text.index("challenges")},
    )
    _roundtrip(
        document,
        "insert_block",
        {
            "chapter_id": str(document.chapters[0].id),
            "index": 1,
            "block": {"type": "marker", "kind": "SOURCE_NEEDED", "note": "Evidence"},
        },
    )


def test_cross_chapter_move_uses_whole_document_inverse() -> None:
    document = _document()
    moving = document.chapters[0].blocks[0]
    result = apply_command(
        document,
        "move_block",
        {
            "block_id": str(moving.id),
            "to_chapter_id": str(document.chapters[1].id),
            "to_index": 1,
        },
    )
    assert result.inverse_command["command_type"] == "restore_document"
    restored = apply_command(
        result.document,
        "restore_document",
        result.inverse_command["payload"],
        allow_internal=True,
    )
    assert restored.document.model_dump(mode="json") == document.model_dump(mode="json")


def test_locked_chapter_rejects_content_edits() -> None:
    document = _document()
    document.chapters[0].status = "locked"
    block = document.chapters[0].blocks[0]
    with pytest.raises(CommandError, match="locked"):
        apply_command(
            document,
            "update_block_text",
            {"block_id": str(block.id), "text": "Should fail"},
        )


def test_type_conversion_preserves_text_and_identity() -> None:
    document = _document()
    block = document.chapters[0].blocks[0]
    expected_text = "".join(run.text for run in block.runs)
    result = apply_command(
        document,
        "change_block_type",
        {"block_id": str(block.id), "target_type": "block_quote", "citation": "Achebe 45"},
    )
    converted = result.document.chapters[0].blocks[0]
    assert converted.id == block.id
    assert converted.text == expected_text
    assert converted.citation == "Achebe 45"


def test_batch_has_one_exact_document_inverse() -> None:
    document = _document()
    first = document.chapters[0].blocks[0]
    result = apply_command(
        document,
        "batch",
        {
            "commands": [
                {
                    "command_type": "update_block_text",
                    "payload": {"block_id": str(first.id), "text": "Batch edit"},
                },
                {
                    "command_type": "update_metadata",
                    "payload": {"path": "guide.name", "value": "Dr. Devi"},
                },
            ]
        },
    )
    assert result.inverse_command["command_type"] == "restore_document"
    restored = apply_command(
        result.document,
        "restore_document",
        result.inverse_command["payload"],
        allow_internal=True,
    )
    assert restored.document.model_dump(mode="json") == document.model_dump(mode="json")


def test_review_fingerprint_ignores_fragile_block_index() -> None:
    block_id = uuid4()
    chapter_id = uuid4()
    first = _fingerprint(
        "quote_unverified",
        {"chapter": 3, "chapter_id": str(chapter_id), "block_id": str(block_id), "block_index": 7},
        None,
    )
    second = _fingerprint(
        "quote_unverified",
        {"chapter": 3, "chapter_id": str(chapter_id), "block_id": str(block_id), "block_index": 18},
        None,
    )
    assert first == second
