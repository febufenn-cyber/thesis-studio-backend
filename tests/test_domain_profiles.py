"""Document-structure profiles (Seam 2): registration, style validity, required sections."""

from __future__ import annotations

import pytest

from app.domains.profiles import (
    UnknownDomainProfile,
    available_domain_profiles,
    get_domain_profile,
)

_KEYS = (
    "ma_dissertation",
    "phd_thesis",
    "ieee_conference_paper",
    "engineering_project_report",
    "imrad_journal_article",
)


def test_get_domain_profile_returns_each_profile():
    for key in _KEYS:
        assert get_domain_profile(key).key == key


def test_unknown_key_raises():
    with pytest.raises(UnknownDomainProfile):
        get_domain_profile("no_such_profile")


def test_every_default_style_is_registered():
    for key in _KEYS:
        assert get_domain_profile(key).validate_style() is True


def test_phd_thesis_requires_declaration_of_ai_use():
    assert "declaration_of_ai_use" in get_domain_profile("phd_thesis").required_sections()


def test_ieee_conference_paper_requires_reproducibility_checklist():
    assert "reproducibility_checklist" in get_domain_profile("ieee_conference_paper").required_sections()


def test_available_domain_profiles_lists_all():
    # The core five must be present; venue templates (test_venue_profiles) add more.
    assert set(_KEYS) <= {p["key"] for p in available_domain_profiles()}
