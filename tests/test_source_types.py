"""Style-agnostic source_type mapping."""

from __future__ import annotations

from app.renderers.source_types import source_type_for_kind


def test_source_type_for_kind_all_registry_kinds():
    assert source_type_for_kind("book") == "book"
    assert source_type_for_kind("translated_book") == "book"
    assert source_type_for_kind("journal") == "article"
    assert source_type_for_kind("journal_db") == "article"
    assert source_type_for_kind("chapter_in_collection") == "chapter"
    assert source_type_for_kind("web") == "webpage"
    assert source_type_for_kind("film") == "film"


def test_source_type_for_kind_unknown_falls_back_to_other():
    assert source_type_for_kind("unknown") == "other"
    assert source_type_for_kind("") == "other"
    assert source_type_for_kind("dataset") == "other"
