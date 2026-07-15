"""Venue-compliance validators (docs/LLD.md 3.4)."""

from __future__ import annotations

import pytest

from app.canonical.model import ThesisDocument
from app.domains.profiles import get_domain_profile
from app.domains.validators import (
    ComplianceContext,
    PageInfo,
    UnknownValidator,
    get_validator,
    run_profile,
)


def _doc(chapters=None, front_matter=None) -> ThesisDocument:
    return ThesisDocument.model_validate(
        {
            "meta": {},
            "front_matter": front_matter or [],
            "chapters": chapters or [],
            "works_cited": [],
        }
    )


def _ctx(document, profile, *, pages=None, answers=None, present=frozenset()) -> ComplianceContext:
    return ComplianceContext(
        document=document,
        profile=profile,
        page_info=PageInfo(page_count=pages, measured_by="pdf" if pages else "estimate"),
        reproducibility_answers=answers or {},
        present_sections=present,
    )


def _para(text: str) -> dict:
    return {"type": "paragraph", "runs": [{"text": text}]}


def test_unknown_validator_raises() -> None:
    with pytest.raises(UnknownValidator):
        get_validator("nope")


def test_page_budget_blocks_when_measured_over_limit() -> None:
    profile = get_domain_profile("neurips_paper")  # limit 9
    doc = _doc(chapters=[{"number": 1, "title": "M", "blocks": [_para("x")]}])
    findings = get_validator("page_budget").validate(_ctx(doc, profile, pages=12))
    assert any(f.code == "over_page_limit" and f.severity == "block" for f in findings)


def test_page_budget_estimate_warns_only() -> None:
    profile = get_domain_profile("neurips_paper")
    huge = " ".join(["word"] * 20000)  # ~22 pages estimated
    doc = _doc(chapters=[{"number": 1, "title": "M", "blocks": [_para(huge)]}])
    findings = get_validator("page_budget").validate(_ctx(doc, profile))
    assert any(f.code == "over_page_limit" and f.severity == "warn" for f in findings)


def test_double_blind_flags_link_email_and_acknowledgement() -> None:
    profile = get_domain_profile("cvpr_paper")
    doc = _doc(
        chapters=[{"number": 1, "title": "M", "blocks": [_para("Code at https://github.com/me/x, mail a@b.com")]}],
        front_matter=[{"kind": "acknowledgement", "body_blocks": [_para("Thanks")]}],
    )
    findings = get_validator("double_blind").validate(_ctx(doc, profile))
    codes = {f.code for f in findings}
    assert {"deanonymizing_link", "email_present", "acknowledgement_present"} <= codes


def test_double_blind_allows_anonymized_link() -> None:
    profile = get_domain_profile("cvpr_paper")
    doc = _doc(chapters=[{"number": 1, "title": "M", "blocks": [_para("Code at https://anonymous.4open.science/r/abc")]}])
    findings = get_validator("double_blind").validate(_ctx(doc, profile))
    assert not any(f.code == "deanonymizing_link" for f in findings)


def test_reproducibility_blocks_missing_section() -> None:
    profile = get_domain_profile("neurips_paper")
    doc = _doc(chapters=[{"number": 1, "title": "M", "blocks": [_para("x")]}])
    findings = get_validator("reproducibility").validate(_ctx(doc, profile, present=frozenset()))
    assert any(f.code == "reproducibility_section_missing" for f in findings)


def test_reproducibility_passes_with_sections_present() -> None:
    profile = get_domain_profile("neurips_paper")
    doc = _doc(chapters=[{"number": 1, "title": "M", "blocks": [_para("x")]}])
    present = frozenset({"reproducibility_checklist", "broader_impacts"})
    findings = get_validator("reproducibility").validate(_ctx(doc, profile, present=present))
    assert findings == []


def test_run_profile_runs_all_declared_validators() -> None:
    profile = get_domain_profile("neurips_paper")
    doc = _doc(chapters=[{"number": 1, "title": "M", "blocks": [_para("clean body")]}])
    findings = run_profile(_ctx(doc, profile, pages=3, present=frozenset({"reproducibility_checklist", "broader_impacts"})))
    # Clean, within limit, sections present -> no blocks.
    assert not any(f.severity == "block" for f in findings)
