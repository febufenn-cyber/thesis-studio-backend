"""Semantic diff between document versions (docs/LLD.md 3.6)."""

from __future__ import annotations

from uuid import uuid4

from app.canonical.model import ThesisDocument
from app.collaboration.semantic_diff import semantic_diff


def _doc(blocks) -> ThesisDocument:
    return ThesisDocument.model_validate(
        {"meta": {}, "front_matter": [], "chapters": [{"number": 1, "title": "C", "blocks": blocks}], "works_cited": []}
    )


def _p(bid: str, text: str) -> dict:
    return {"id": bid, "type": "paragraph", "runs": [{"text": text}]}


def test_meaning_change_vs_formatting_only() -> None:
    a, b = str(uuid4()), str(uuid4())
    base = _doc([_p(a, "X causes Y"), _p(b, "stable claim")])
    head = _doc([_p(a, "X may correlate with Y"), _p(b, "stable claim.")])
    result = semantic_diff(base, head)
    changes = {e.block_id: e.change for e in result.entries}
    assert changes[a] == "meaning_changed"
    assert changes[b] == "formatting_only"


def test_added_and_removed() -> None:
    a, b, c = str(uuid4()), str(uuid4()), str(uuid4())
    base = _doc([_p(a, "one"), _p(b, "two")])
    head = _doc([_p(a, "one"), _p(c, "three")])
    result = semantic_diff(base, head)
    changes = {e.block_id: e.change for e in result.entries}
    assert changes[c] == "added"
    assert changes[b] == "removed"
    assert changes[a] == "unchanged"


def test_moved_block() -> None:
    a, b = str(uuid4()), str(uuid4())
    base = _doc([_p(a, "first"), _p(b, "second")])
    head = _doc([_p(b, "second"), _p(a, "first")])
    result = semantic_diff(base, head)
    changes = {e.block_id: e.change for e in result.entries}
    assert changes[a] == "moved"
    assert changes[b] == "moved"


def test_identical_is_all_unchanged() -> None:
    a = str(uuid4())
    doc = _doc([_p(a, "same")])
    result = semantic_diff(doc, doc)
    assert result.summary == {"unchanged": 1}
