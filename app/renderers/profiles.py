"""Format-profile resolution for the Thesis Studio renderers.

Defines `ResolvedProfile` (a frozen dataclass tree mirroring FORMAT_SPEC §8 keys)
and two built-in singleton profiles — ``TN_UNIVERSITY`` and ``MLA_STRICT`` — plus
the public ``resolve_profile()`` function that deep-merges a StyleProfile JSON
override onto a named base.

Usage::

    from app.renderers.profiles import resolve_profile

    profile = resolve_profile("tn_university", project.style_profile_json)
    font = profile.type.font          # "Times New Roman"
    left = profile.page.margins_in.left  # 1.5 (inches)

See FORMAT_SPEC.md §1 (built-in values) and §8 (override JSON schema).
"""

from __future__ import annotations

import copy
import dataclasses
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Nested dataclasses — frozen so the module-level singletons can't be mutated.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarginsIn:
    """Page margins, all in inches."""

    top: float
    bottom: float
    left: float
    right: float


@dataclass(frozen=True)
class PageConfig:
    """Paper size and margins."""

    size: str  # "A4" | "Letter"
    margins_in: MarginsIn


@dataclass(frozen=True)
class TypeConfig:
    """Typography settings applied to body text and (by default) all other text."""

    font: str
    size_pt: int
    line_spacing: float
    justify_body: bool
    first_line_indent_in: float


@dataclass(frozen=True)
class PaginationSide:
    """Pagination settings for one side (front matter or body).

    ``style`` is one of ``"lower_roman"``, ``"upper_roman"``, ``"arabic"``.
    ``position`` is one of ``"footer_center"``, ``"header_right"``.
    ``restart_at`` (body only) is the integer page number where counting restarts.
    """

    style: str
    position: str
    restart_at: int | None = None


@dataclass(frozen=True)
class PaginationConfig:
    """Complete pagination specification."""

    front: PaginationSide
    body: PaginationSide
    mla_header_name: bool  # True → body header reads "Surname {PAGE}"


@dataclass(frozen=True)
class ChapterLabelConfig:
    """How chapter labels are rendered above each chapter title."""

    format: str       # e.g. "CHAPTER {ROMAN}"
    title_caps: bool  # True → chapter title uppercased
    title_bold: bool
    new_page: bool    # True → each chapter starts on a fresh page


@dataclass(frozen=True)
class H2Config:
    """Style for level-2 (section) headings — bold and/or case transformation."""

    bold: bool
    case: str  # "title" | "upper" | "lower"


@dataclass(frozen=True)
class H3Config:
    """Style for level-3 (sub-section) headings — italic and/or case transformation."""

    italic: bool
    case: str  # "title" | "upper" | "lower"


@dataclass(frozen=True)
class HeadingsConfig:
    """Heading numbering and per-level styles."""

    numbered: bool  # True → 1.1 / 1.1.1 prefix
    h2: H2Config
    h3: H3Config


@dataclass(frozen=True)
class QuotesConfig:
    """Thresholds and indentation for quotation blocks."""

    block_threshold_lines: int   # prose quotes ≥ this → block quote
    block_indent_in: float       # left indent for block quotes, inches
    verse_threshold_lines: int   # verse lines ≥ this → verse block


@dataclass(frozen=True)
class WorksCitedConfig:
    """Works Cited section formatting."""

    heading: str            # e.g. "WORKS CITED" or "Works Cited"
    heading_bold: bool
    hanging_indent_in: float
    bibliography_label: bool  # True → print a sub-label before entries


@dataclass(frozen=True)
class LogoConfig:
    """College logo placement on the title page."""

    width_in: float  # rendered width in inches


@dataclass(frozen=True)
class TocConfig:
    """Table of Contents generation options."""

    dot_leaders: bool         # True → tab-leader dots between title and page number
    native_word_field: bool   # True → emit a native Word TOC field (user updates)


@dataclass(frozen=True)
class ResolvedProfile:
    """Complete, resolved format profile consumed by all renderers.

    Mirrors FORMAT_SPEC §8 keys exactly.  Obtain via ``resolve_profile()``
    rather than constructing directly.
    """

    page: PageConfig
    type: TypeConfig
    pagination: PaginationConfig
    front_matter_order: tuple[str, ...]
    chapter_label: ChapterLabelConfig
    headings: HeadingsConfig
    quotes: QuotesConfig
    works_cited: WorksCitedConfig
    logo: LogoConfig
    toc: TocConfig
    notes: str  # free-text: deviations the analyzer couldn't encode


# ---------------------------------------------------------------------------
# Built-in profiles (FORMAT_SPEC §1)
# ---------------------------------------------------------------------------

TN_UNIVERSITY: ResolvedProfile = ResolvedProfile(
    page=PageConfig(
        size="A4",
        margins_in=MarginsIn(top=1.0, bottom=1.0, left=1.5, right=1.0),
    ),
    type=TypeConfig(
        font="Times New Roman",
        size_pt=12,
        line_spacing=2.0,
        justify_body=True,
        first_line_indent_in=0.5,
    ),
    pagination=PaginationConfig(
        front=PaginationSide(style="lower_roman", position="footer_center"),
        body=PaginationSide(style="arabic", position="footer_center", restart_at=1),
        mla_header_name=False,
    ),
    front_matter_order=(
        "title_page",
        "certificate",
        "declaration",
        "acknowledgement",
        "contents",
    ),
    chapter_label=ChapterLabelConfig(
        format="CHAPTER {ROMAN}",
        title_caps=True,
        title_bold=True,
        new_page=True,
    ),
    headings=HeadingsConfig(
        numbered=False,
        h2=H2Config(bold=True, case="title"),
        h3=H3Config(italic=True, case="title"),
    ),
    quotes=QuotesConfig(
        block_threshold_lines=4,
        block_indent_in=0.5,
        verse_threshold_lines=3,
    ),
    works_cited=WorksCitedConfig(
        heading="WORKS CITED",
        heading_bold=True,
        hanging_indent_in=0.5,
        bibliography_label=False,
    ),
    logo=LogoConfig(width_in=1.2),
    toc=TocConfig(dot_leaders=True, native_word_field=False),
    notes="",
)

MLA_STRICT: ResolvedProfile = ResolvedProfile(
    page=PageConfig(
        size="Letter",
        margins_in=MarginsIn(top=1.0, bottom=1.0, left=1.0, right=1.0),
    ),
    type=TypeConfig(
        font="Times New Roman",
        size_pt=12,
        line_spacing=2.0,
        justify_body=False,
        first_line_indent_in=0.5,
    ),
    pagination=PaginationConfig(
        front=PaginationSide(style="arabic", position="header_right"),
        body=PaginationSide(style="arabic", position="header_right", restart_at=1),
        mla_header_name=True,
    ),
    front_matter_order=(),  # MLA uses a first-page heading block, no separate pages
    chapter_label=ChapterLabelConfig(
        format="{ROMAN}",
        title_caps=False,
        title_bold=False,
        new_page=True,
    ),
    headings=HeadingsConfig(
        numbered=False,
        h2=H2Config(bold=True, case="title"),
        h3=H3Config(italic=True, case="title"),
    ),
    quotes=QuotesConfig(
        block_threshold_lines=4,
        block_indent_in=0.5,
        verse_threshold_lines=3,
    ),
    works_cited=WorksCitedConfig(
        heading="Works Cited",
        heading_bold=False,
        hanging_indent_in=0.5,
        bibliography_label=False,
    ),
    logo=LogoConfig(width_in=1.2),
    toc=TocConfig(dot_leaders=True, native_word_field=False),
    notes="",
)

_BUILTINS: dict[str, ResolvedProfile] = {
    "tn_university": TN_UNIVERSITY,
    "mla_strict": MLA_STRICT,
}

# Top-level keys in the StyleProfile JSON that are record metadata, not style knobs.
# These are silently ignored rather than collected as "unknown".
_METADATA_KEYS: frozenset[str] = frozenset({"id", "name", "base"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _recursive_merge(
    base: dict[str, Any],
    override: dict[str, Any],
    ignore_keys: frozenset[str],
    unknown: list[str],
    path: str,
) -> None:
    """Deep-merge *override* into *base* in-place.

    - Known scalar keys: replaced.
    - Known dict-valued keys: recurse into them.
    - Keys in *ignore_keys*: silently skipped.
    - Any other key at any nesting level: its dotted path is appended to *unknown*.
    """
    for key, val in override.items():
        if key in ignore_keys:
            continue
        full_key = f"{path}{key}" if path else key
        if key not in base:
            unknown.append(full_key)
            continue
        if isinstance(val, dict) and isinstance(base[key], dict):
            _recursive_merge(base[key], val, frozenset(), unknown, f"{full_key}.")
        else:
            base[key] = val


def _profile_from_dict(d: dict[str, Any]) -> ResolvedProfile:
    """Reconstruct a ResolvedProfile from a nested dict (as produced by dataclasses.asdict)."""
    pg = d["page"]
    ty = d["type"]
    pa = d["pagination"]
    cl = d["chapter_label"]
    hd = d["headings"]

    # front_matter_order may be a list (from asdict) or tuple; normalise to tuple.
    fmt_order = tuple(d["front_matter_order"])

    return ResolvedProfile(
        page=PageConfig(
            size=pg["size"],
            margins_in=MarginsIn(
                top=pg["margins_in"]["top"],
                bottom=pg["margins_in"]["bottom"],
                left=pg["margins_in"]["left"],
                right=pg["margins_in"]["right"],
            ),
        ),
        type=TypeConfig(
            font=ty["font"],
            size_pt=ty["size_pt"],
            line_spacing=ty["line_spacing"],
            justify_body=ty["justify_body"],
            first_line_indent_in=ty["first_line_indent_in"],
        ),
        pagination=PaginationConfig(
            front=PaginationSide(
                style=pa["front"]["style"],
                position=pa["front"]["position"],
                restart_at=pa["front"].get("restart_at"),
            ),
            body=PaginationSide(
                style=pa["body"]["style"],
                position=pa["body"]["position"],
                restart_at=pa["body"].get("restart_at"),
            ),
            mla_header_name=pa["mla_header_name"],
        ),
        front_matter_order=fmt_order,
        chapter_label=ChapterLabelConfig(
            format=cl["format"],
            title_caps=cl["title_caps"],
            title_bold=cl["title_bold"],
            new_page=cl["new_page"],
        ),
        headings=HeadingsConfig(
            numbered=hd["numbered"],
            h2=H2Config(bold=hd["h2"]["bold"], case=hd["h2"]["case"]),
            h3=H3Config(italic=hd["h3"]["italic"], case=hd["h3"]["case"]),
        ),
        quotes=QuotesConfig(
            block_threshold_lines=d["quotes"]["block_threshold_lines"],
            block_indent_in=d["quotes"]["block_indent_in"],
            verse_threshold_lines=d["quotes"]["verse_threshold_lines"],
        ),
        works_cited=WorksCitedConfig(
            heading=d["works_cited"]["heading"],
            heading_bold=d["works_cited"]["heading_bold"],
            hanging_indent_in=d["works_cited"]["hanging_indent_in"],
            bibliography_label=d["works_cited"]["bibliography_label"],
        ),
        logo=LogoConfig(width_in=d["logo"]["width_in"]),
        toc=TocConfig(
            dot_leaders=d["toc"]["dot_leaders"],
            native_word_field=d["toc"]["native_word_field"],
        ),
        notes=d["notes"],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_profile(
    base_name: str,
    style_profile_json: dict[str, Any] | None,
) -> ResolvedProfile:
    """Return a ResolvedProfile by deep-merging *style_profile_json* onto *base_name*.

    Parameters
    ----------
    base_name:
        One of ``"tn_university"`` or ``"mla_strict"``.
    style_profile_json:
        The ``StyleProfile`` JSON dict (FORMAT_SPEC §8).  ``None`` or empty dict
        returns the base profile unchanged.

    Returns
    -------
    ResolvedProfile
        A new, frozen ResolvedProfile.  The module-level singletons are never
        mutated.

    Raises
    ------
    ValueError
        If *base_name* is not a recognised built-in profile name.

    Notes
    -----
    Merge semantics:

    - Nested dicts (``page``, ``type``, ``pagination`` …) are deep-merged, so a
      partial override changes only the supplied sub-keys.
    - Unknown keys at any nesting level are collected and appended to
      ``ResolvedProfile.notes`` as ``"Unknown keys: <dotted-path>, …"``.
    - Top-level record-metadata keys (``id``, ``name``, ``base``) are silently
      ignored — they are not style knobs.
    """
    if base_name not in _BUILTINS:
        raise ValueError(
            f"Unknown base profile {base_name!r}. Available: {sorted(_BUILTINS)}"
        )

    base_profile = copy.deepcopy(_BUILTINS[base_name])

    if not style_profile_json:
        return base_profile

    # Work on a mutable nested-dict copy so we never touch the frozen singleton.
    base_dict: dict[str, Any] = dataclasses.asdict(base_profile)
    unknown_keys: list[str] = []

    _recursive_merge(base_dict, style_profile_json, _METADATA_KEYS, unknown_keys, path="")

    if unknown_keys:
        current = base_dict.get("notes") or ""
        extra = f"Unknown keys: {', '.join(sorted(unknown_keys))}"
        base_dict["notes"] = f"{current}; {extra}" if current else extra

    return _profile_from_dict(base_dict)
