"""Disclosure-template rendering and fail-closed lookup (docs/LLD.md 3.1)."""

from __future__ import annotations

import pytest

from app.provenance.rollup import ProvenanceRollup
from app.provenance.templates import (
    UnknownDisclosureTemplate,
    default_template_key,
    get_disclosure_template,
    list_disclosure_templates,
)


def _assisted() -> ProvenanceRollup:
    return ProvenanceRollup(
        origin_counts={"human": 3, "ai_proposal": 2},
        total_blocks=5,
        assisted=True,
        accepted_proposals=1,
        accepted_operations=2,
        human_edited_operations=1,
        models=["claude-x"],
    )


def _unassisted() -> ProvenanceRollup:
    return ProvenanceRollup(
        origin_counts={"human": 5}, total_blocks=5, assisted=False,
        accepted_proposals=0, accepted_operations=0, human_edited_operations=0,
    )


def test_unknown_template_fails_closed() -> None:
    with pytest.raises(UnknownDisclosureTemplate):
        get_disclosure_template("nope")


def test_default_template_registered() -> None:
    keys = {t["key"] for t in list_disclosure_templates()}
    assert default_template_key() in keys
    assert {"generic_university", "neurips", "elsevier"} <= keys


def test_assisted_statement_names_tools_and_counts() -> None:
    body = get_disclosure_template("neurips").render(_assisted(), "My Paper")
    assert "claude-x" in body
    assert "2 operation" in body
    assert "responsibility" in body.lower()


def test_unassisted_statement_declares_no_ai() -> None:
    generic = get_disclosure_template("generic_university").render(_unassisted(), "My Thesis")
    assert "No AI-assisted" in generic
    elsevier = get_disclosure_template("elsevier").render(_unassisted(), "My Thesis")
    assert "no" in elsevier.lower() and "generative ai" in elsevier.lower()
