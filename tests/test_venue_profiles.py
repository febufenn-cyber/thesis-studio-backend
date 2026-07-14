"""Venue-template DomainProfiles (NeurIPS / ACL / CVPR)."""

from __future__ import annotations

from app.domains.profiles import available_domain_profiles, get_domain_profile


def test_new_venue_profiles_are_registered():
    for key in ("neurips_paper", "acl_paper", "cvpr_paper"):
        assert get_domain_profile(key).key == key


def test_neurips_requires_broader_impacts_and_reproducibility():
    required = get_domain_profile("neurips_paper").required_sections()
    assert "broader_impacts" in required
    assert "reproducibility_checklist" in required


def test_acl_requires_limitations_and_ethics_statement():
    required = get_domain_profile("acl_paper").required_sections()
    assert "limitations" in required
    assert "ethics_statement" in required


def test_new_profiles_default_style_validates():
    for key in ("neurips_paper", "acl_paper", "cvpr_paper"):
        prof = get_domain_profile(key)
        assert prof.default_citation_style == "ieee-2021"
        assert prof.validate_style() is True


def test_available_domain_profiles_includes_new_venues():
    keys = {p["key"] for p in available_domain_profiles()}
    assert {"neurips_paper", "acl_paper", "cvpr_paper"} <= keys
