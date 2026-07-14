"""Type-aware citation field schema (style-agnostic validation surface)."""

from __future__ import annotations

from app.renderers.field_schema import all_kinds, field_schema_for_kind, missing_required


def test_journal_schema_source_type_and_required():
    schema = field_schema_for_kind("journal")
    assert schema["kind"] == "journal"
    assert schema["source_type"] == "article"
    assert "container" in schema["required"]
    assert "volume" in schema["required"]


def test_missing_required_reports_absent_fields():
    assert set(missing_required("book", {"author": "X", "title": "Y"})) == {"publisher", "year"}


def test_missing_required_flags_verify_placeholder():
    fields = {"author": "X", "title": "Y", "publisher": "[VERIFY] Press", "year": "2020"}
    assert missing_required("book", fields) == ["publisher"]


def test_missing_required_flags_blank_value():
    fields = {"author": "X", "title": "Y", "publisher": "   ", "year": ""}
    assert missing_required("book", fields) == ["publisher", "year"]


def test_all_kinds_includes_registry_kinds():
    kinds = set(all_kinds())
    assert {
        "book", "translated_book", "chapter_in_collection",
        "journal", "journal_db", "web", "film",
    } <= kinds
