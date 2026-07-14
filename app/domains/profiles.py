"""Document-structure profiles (Seam 2 of the domain expansion).

A :class:`DomainProfile` binds three orthogonal things that Acadensia currently
hardcodes around the MA dissertation:

* a **section template** — an ordered tuple of :class:`SectionSpec` nodes, each
  marked required/optional and single/repeatable (the natural generalization of
  the ``FrontMatterEntry`` + ``ChapterDoc`` structure);
* a **default citation style** — a key into the citation-style registry
  (``app.renderers.styles``), overridable per document; and
* a **submission-readiness checklist** — human-facing artifacts/sections that
  must exist before export.

This module is deliberately self-contained and DB-free: pure data plus lookup
helpers. See ``docs/DOMAIN_EXPANSION.md`` Part 2 and Seam 2 in Part 4.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.renderers.styles import UnknownCitationStyle, get_citation_style


@dataclass(frozen=True)
class SectionSpec:
    """One node in a profile's section-graph template."""

    name: str
    required: bool = True
    repeatable: bool = False


@dataclass(frozen=True)
class DomainProfile:
    """A credential/output's document skeleton and submission rules."""

    key: str
    label: str
    credential: str
    default_citation_style: str
    sections: tuple[SectionSpec, ...]
    submission_checklist: tuple[str, ...]

    def required_sections(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.sections if s.required)

    def validate_style(self) -> bool:
        try:
            get_citation_style(self.default_citation_style)
        except UnknownCitationStyle:
            return False
        return True


class UnknownDomainProfile(KeyError):
    """The requested domain-profile key is not registered."""


_MA_DISSERTATION = DomainProfile(
    key="ma_dissertation",
    label="MA Dissertation",
    credential="MA / MPhil dissertation",
    default_citation_style="mla-9",
    sections=(
        SectionSpec("title_page"),
        SectionSpec("certificate"),
        SectionSpec("declaration"),
        SectionSpec("acknowledgement", required=False),
        SectionSpec("contents"),
        SectionSpec("chapters", repeatable=True),
        SectionSpec("works_cited"),
    ),
    submission_checklist=(
        "Signed certificate present",
        "Signed declaration of originality present",
        "Table of contents matches chapter headings",
        "Every in-text citation resolves to a Works Cited entry",
    ),
)

_PHD_THESIS = DomainProfile(
    key="phd_thesis",
    label="PhD Thesis",
    credential="Doctoral thesis",
    default_citation_style="chicago-ad-17",
    sections=(
        SectionSpec("title_page"),
        SectionSpec("certificate"),
        SectionSpec("declaration"),
        SectionSpec("declaration_of_ai_use"),
        SectionSpec("abstract"),
        SectionSpec("acknowledgement", required=False),
        SectionSpec("contents"),
        SectionSpec("list_of_publications", required=False),
        SectionSpec("literature_review"),
        SectionSpec("methodology"),
        SectionSpec("chapters", repeatable=True),
        SectionSpec("contribution_statement"),
        SectionSpec("works_cited"),
        SectionSpec("appendices", required=False),
    ),
    submission_checklist=(
        "Declaration of AI use completed and attached",
        "Abstract present (and translated where required)",
        "Contribution statement present",
        "List of publications reconciled with the thesis-by-publication chapters",
        "Every in-text citation resolves to a reference entry",
    ),
)

_IEEE_CONFERENCE_PAPER = DomainProfile(
    key="ieee_conference_paper",
    label="IEEE Conference Paper",
    credential="Conference paper (CS/AI)",
    default_citation_style="ieee-2021",
    sections=(
        SectionSpec("title"),
        SectionSpec("abstract"),
        SectionSpec("keywords"),
        SectionSpec("introduction"),
        SectionSpec("methods"),
        SectionSpec("results"),
        SectionSpec("discussion"),
        SectionSpec("conclusion"),
        SectionSpec("references"),
        SectionSpec("reproducibility_checklist"),
        SectionSpec("ethics_statement", required=False),
    ),
    submission_checklist=(
        "Reproducibility checklist completed",
        "Ethics / broader-impact statement addressed",
        "Within the venue page limit",
        "Every in-text citation resolves to a numbered reference",
    ),
)

_ENGINEERING_PROJECT_REPORT = DomainProfile(
    key="engineering_project_report",
    label="Engineering Project Report",
    credential="Engineering project / capstone report",
    default_citation_style="ieee-2021",
    sections=(
        SectionSpec("abstract"),
        SectionSpec("problem_statement"),
        SectionSpec("requirements"),
        SectionSpec("design"),
        SectionSpec("implementation"),
        SectionSpec("testing_results"),
        SectionSpec("discussion"),
        SectionSpec("conclusion"),
        SectionSpec("references"),
        SectionSpec("appendices", required=False),
    ),
    submission_checklist=(
        "Requirements traced to design and testing",
        "Testing/results section reports measured outcomes",
        "Appendices (code, schematics, BOM) attached where applicable",
        "Every in-text citation resolves to a numbered reference",
    ),
)

_IMRAD_JOURNAL_ARTICLE = DomainProfile(
    key="imrad_journal_article",
    label="IMRaD Journal Article",
    credential="Journal article",
    default_citation_style="vancouver-icmje",
    sections=(
        SectionSpec("title"),
        SectionSpec("abstract"),
        SectionSpec("keywords"),
        SectionSpec("introduction"),
        SectionSpec("methods"),
        SectionSpec("results"),
        SectionSpec("discussion"),
        SectionSpec("references"),
    ),
    submission_checklist=(
        "Structured abstract present",
        "Methods sufficient to reproduce the study",
        "Every in-text citation resolves to a numbered reference",
    ),
)


_PROFILES: dict[str, DomainProfile] = {
    p.key: p
    for p in (
        _MA_DISSERTATION,
        _PHD_THESIS,
        _IEEE_CONFERENCE_PAPER,
        _ENGINEERING_PROJECT_REPORT,
        _IMRAD_JOURNAL_ARTICLE,
    )
}


def get_domain_profile(key: str) -> DomainProfile:
    """Return the profile for ``key``. Raises :class:`UnknownDomainProfile`."""
    try:
        return _PROFILES[key]
    except KeyError as exc:
        raise UnknownDomainProfile(
            f"Unknown domain profile {key!r}; available: {sorted(_PROFILES)}"
        ) from exc


def available_domain_profiles() -> list[dict[str, str]]:
    """Metadata for every registered profile (for UI/profile pickers)."""
    return [
        {
            "key": p.key,
            "label": p.label,
            "credential": p.credential,
            "default_citation_style": p.default_citation_style,
        }
        for p in _PROFILES.values()
    ]


__all__ = [
    "SectionSpec",
    "DomainProfile",
    "UnknownDomainProfile",
    "get_domain_profile",
    "available_domain_profiles",
]
