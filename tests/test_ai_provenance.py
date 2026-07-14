"""Provenance & attribution invariants for the canonical model and command engine.

Covers two changes:
  * the editorial marker vocabulary is a single source of truth shared by the
    canonical model and the AI proposal validator (they can no longer drift);
  * every structural block records an ``origin`` (manuscript_import / human /
    ai_proposal), populated at apply time and inferred for legacy blocks.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.ai.proposal_engine import _ALLOWED_MARKERS
from app.canonical.model import (
    MARKER_KINDS,
    BlockIdentity,
    ChapterDoc,
    MarkerBlock,
    ParagraphBlock,
    Run,
    ThesisDocument,
)
from app.editor.commands import apply_command


def _doc_with_one_paragraph() -> tuple[ThesisDocument, str, str]:
    block = ParagraphBlock(runs=[Run(text="Existing sentence.")], origin="human")
    chapter = ChapterDoc(number=1, title="One", blocks=[block])
    document = ThesisDocument(chapters=[chapter])
    return document, str(chapter.id), str(block.id)


def test_marker_vocabulary_is_a_single_source_of_truth() -> None:
    # The bug: the proposal validator accepted marker kinds the model rejected,
    # so an accepted proposal crashed when the MarkerBlock was constructed.
    assert _ALLOWED_MARKERS == MARKER_KINDS
    for kind in MARKER_KINDS:
        # Each allowed kind must build a valid MarkerBlock — no apply-time crash.
        marker = MarkerBlock(kind=kind, note="x")
        assert marker.kind == kind


@pytest.mark.parametrize("kind", ["STRUCTURE_REVIEW", "EVIDENCE_NEEDED"])
def test_previously_crashing_marker_kinds_now_build(kind: str) -> None:
    assert MarkerBlock(kind=kind, note="needs work").kind == kind


def test_origin_inferred_for_legacy_manuscript_blocks() -> None:
    # A block carrying manuscript provenance but no explicit origin is treated as
    # manuscript-imported (back-compat for documents written before origin tracking).
    identity = BlockIdentity(source_revision_id=uuid4())
    assert identity.origin == "manuscript_import"


def test_origin_defaults_to_none_when_truly_unknown() -> None:
    assert BlockIdentity().origin is None


def test_explicit_origin_is_not_overwritten_by_inference() -> None:
    identity = BlockIdentity(source_revision_id=uuid4(), origin="ai_proposal")
    assert identity.origin == "ai_proposal"


def test_ai_inserted_block_is_attributed_ai_proposal() -> None:
    document, chapter_id, after_id = _doc_with_one_paragraph()
    # Mirrors what proposal_engine._translate_operation emits for insert_paragraph.
    result = apply_command(
        document,
        "insert_block",
        {
            "chapter_id": chapter_id,
            "after_block_id": after_id,
            "block": {"type": "paragraph", "runs": [{"text": "AI text."}], "origin": "ai_proposal"},
        },
    )
    inserted = result.document.chapters[0].blocks[1]
    assert inserted.origin == "ai_proposal"


def test_human_inserted_block_defaults_to_human() -> None:
    document, chapter_id, after_id = _doc_with_one_paragraph()
    result = apply_command(
        document,
        "insert_block",
        {
            "chapter_id": chapter_id,
            "after_block_id": after_id,
            "block": {"type": "paragraph", "runs": [{"text": "Human text."}]},
        },
    )
    inserted = result.document.chapters[0].blocks[1]
    assert inserted.origin == "human"


def test_split_preserves_authorship() -> None:
    document, chapter_id, block_id = _doc_with_one_paragraph()
    result = apply_command(
        document, "split_block", {"block_id": block_id, "offset": len("Existing ")}
    )
    left, right = result.document.chapters[0].blocks[:2]
    assert left.origin == "human"
    assert right.origin == "human"


def test_ai_marker_carries_origin_human_marker_does_not() -> None:
    document, chapter_id, block_id = _doc_with_one_paragraph()
    ai = apply_command(
        document,
        "add_marker",
        {"block_id": block_id, "kind": "STRUCTURE_REVIEW", "note": "reorganise", "origin": "ai_proposal"},
    )
    assert ai.document.chapters[0].blocks[1].origin == "ai_proposal"

    document2, _cid, block_id2 = _doc_with_one_paragraph()
    human = apply_command(
        document2, "add_marker", {"block_id": block_id2, "kind": "REVIEW_REQUIRED", "note": "check"}
    )
    assert human.document.chapters[0].blocks[1].origin is None
