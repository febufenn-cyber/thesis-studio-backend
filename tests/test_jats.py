"""JATS export (docs/LLD.md 3.5)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.canonical.model import ThesisDocument, ThesisMeta, WorksCitedRef
from app.renderers.docx_renderer import RenderError
from app.renderers.jats import to_jats


@dataclass
class _Src:
    kind: str
    fields: dict


def _doc(**kw) -> ThesisDocument:
    payload = {
        "meta": {"title": "On Woolf", "candidate": {"name": "Jane Doe"}},
        "front_matter": [],
        "chapters": [
            {
                "number": 1,
                "title": "Introduction",
                "blocks": [
                    {"type": "paragraph", "runs": [
                        {"text": "A study of "}, {"text": "Mrs Dalloway", "italic": True}
                    ]}
                ],
            }
        ],
        "works_cited": [],
    }
    payload.update(kw)
    return ThesisDocument.model_validate(payload)


def test_jats_is_well_formed_and_has_core_tags() -> None:
    xml = to_jats(_doc(), {})
    ET.fromstring(xml)  # raises if malformed
    assert "<article-title>On Woolf</article-title>" in xml
    assert "<sec><title>Introduction</title>" in xml
    assert "<italic>Mrs Dalloway</italic>" in xml


def test_jats_emits_ref_list() -> None:
    sid = uuid4()
    doc = ThesisDocument(
        meta=ThesisMeta(title="T"),
        works_cited=[WorksCitedRef(source_id=sid)],
    )
    sources = {sid: _Src("book", {"author": "Woolf, Virginia", "title": "Mrs Dalloway", "year": "1925"})}
    xml = to_jats(doc, sources)
    ET.fromstring(xml)
    assert "<ref-list>" in xml
    assert "<article-title>Mrs Dalloway</article-title>" in xml


def test_jats_aborts_on_unresolved_marker() -> None:
    doc = _doc(chapters=[{
        "number": 1, "title": "Intro",
        "blocks": [{"type": "marker", "kind": "VERIFY", "note": "check this"}],
    }])
    with pytest.raises(RenderError):
        to_jats(doc, {})


def test_jats_escapes_special_characters() -> None:
    doc = _doc(chapters=[{
        "number": 1, "title": "A & B",
        "blocks": [{"type": "paragraph", "runs": [{"text": "x < y & z"}]}],
    }])
    xml = to_jats(doc, {})
    ET.fromstring(xml)
    assert "A &amp; B" in xml
    assert "x &lt; y &amp; z" in xml
