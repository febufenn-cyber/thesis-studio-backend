"""Robofox speaks the project's discipline — domain guidance selection."""

from __future__ import annotations

from types import SimpleNamespace

from app.ai.domain_guidance import (
    DOMAIN_GUIDANCE,
    GENERIC_KEY,
    guidance_for_project,
    resolve_domain_key,
)


def _project(meta: dict | None = None, doc_type: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(meta=meta or {}, doc_type=doc_type)


def test_every_domain_has_distinct_substantive_guidance() -> None:
    texts = list(DOMAIN_GUIDANCE.values())
    assert len(texts) == len(set(texts)), "guidance blocks must be distinct"
    for key, text in DOMAIN_GUIDANCE.items():
        assert len(text) > 200, f"{key} guidance too thin to matter"
        assert text.startswith("DISCIPLINE:"), key


def test_playbook_wins_over_doc_type() -> None:
    project = _project(meta={"guide_playbook": "engineering_project_report"},
                       doc_type="ma_dissertation")
    assert resolve_domain_key(project) == "engineering_project_report"


def test_declared_profile_wins_over_doc_type() -> None:
    project = _project(meta={"domain_profile": "neurips_paper"}, doc_type="phd_thesis")
    assert resolve_domain_key(project) == "neurips_paper"


def test_doc_type_fallbacks() -> None:
    assert resolve_domain_key(_project(doc_type="ma_dissertation")) == "ma_dissertation"
    assert resolve_domain_key(_project(doc_type="mphil_dissertation")) == "ma_dissertation"
    assert resolve_domain_key(_project(doc_type="phd_thesis")) == "phd_thesis"
    assert resolve_domain_key(_project(doc_type="project_report")) == "engineering_project_report"


def test_resolution_is_total_never_raises() -> None:
    # Unknown playbook, unknown profile, unknown doc_type, missing attrs.
    assert resolve_domain_key(_project(meta={"guide_playbook": "astrology"})) == GENERIC_KEY
    assert resolve_domain_key(_project(meta={"domain_profile": "nonsense"})) == GENERIC_KEY
    assert resolve_domain_key(_project(doc_type="scroll")) == GENERIC_KEY
    assert resolve_domain_key(SimpleNamespace()) == GENERIC_KEY
    key, text = guidance_for_project(SimpleNamespace(meta=None, doc_type=None))
    assert key == GENERIC_KEY and text


def test_context_compiler_wires_domain_guidance() -> None:
    """The compiled system prompt must carry the DOMAIN GUIDANCE section.

    Wiring check without a database: the compiler module imports the selector
    and interpolates its output into the system prompt template.
    """
    import inspect

    from app.ai import context as ctx

    source = inspect.getsource(ctx)
    assert "guidance_for_project" in source
    assert "DOMAIN GUIDANCE" in source
    assert '"domain_guidance": domain_key' in source  # provenance in manifest
