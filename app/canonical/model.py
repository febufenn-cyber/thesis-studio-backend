"""Canonical ThesisDocument model — the single source of truth for all renderers.

Every renderer (docx, pdf, md, txt) consumes a ThesisDocument instance.
Nothing is rendered from another renderer's output (except PDF which is
produced from the rendered DOCX for fidelity).

M1 deviation note: chapters are stored as JSONB on the Project row rather
than in per-chapter rows.  Per-chapter rows arrive with Mode A gates in M5.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inline text run
# ---------------------------------------------------------------------------


class Run(BaseModel):
    """A contiguous span of text with optional italic emphasis."""

    text: str
    italic: bool = False


# ---------------------------------------------------------------------------
# Block types
# ---------------------------------------------------------------------------


class ParagraphBlock(BaseModel):
    """A body paragraph composed of one or more styled runs."""

    type: Literal["paragraph"]
    runs: list[Run]


class BlockQuoteBlock(BaseModel):
    """A prose quotation longer than four typed lines (FORMAT_SPEC §5).

    Block quotes are indented 0.5", no quotation marks, no first-line indent.
    ``quote_id`` must resolve to a verified registry entry before export.
    """

    type: Literal["block_quote"]
    text: str
    citation: str = ""
    quote_id: UUID | None = None


class VerseQuoteBlock(BaseModel):
    """A verse quotation longer than three lines (FORMAT_SPEC §5).

    Original lineation and capitalization are preserved exactly.
    ``quote_id`` must resolve to a verified registry entry before export.
    """

    type: Literal["verse_quote"]
    lines: list[str]
    citation: str = ""
    quote_id: UUID | None = None


class HeadingBlock(BaseModel):
    """A section heading within a chapter body.

    ``level`` is constrained to 2 or 3 (FORMAT_SPEC §4).  Level-2 headings
    are bold title-case; level-3 are italic title-case.
    """

    type: Literal["heading"]
    level: Literal[2, 3]
    text: str


class MarkerBlock(BaseModel):
    """An unresolved placeholder inserted by DRAFT_PARTNER.

    ``QUOTE_NEEDED`` — a quotation is required here but no registry entry has
    been assigned yet.  Blocks export.
    ``VERIFY`` — a source or fact needs confirmation before export.
    """

    type: Literal["marker"]
    kind: Literal["QUOTE_NEEDED", "VERIFY"]
    note: str


# Discriminated union on the ``type`` field.  Pydantic v2 uses the
# Annotated + Field(discriminator=...) form for proper model_rebuild support.
Block = Annotated[
    Union[
        ParagraphBlock,
        BlockQuoteBlock,
        VerseQuoteBlock,
        HeadingBlock,
        MarkerBlock,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Chapter
# ---------------------------------------------------------------------------


class ChapterDoc(BaseModel):
    """One chapter of the thesis, represented as an ordered list of blocks."""

    number: int
    title: str
    status: Literal["draft", "review", "approved"] = "draft"
    blocks: list[Block] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------


class FrontMatterEntry(BaseModel):
    """One front-matter section in its canonical order (FORMAT_SPEC §3).

    ``kind`` drives the renderer's template selection.
    ``body_blocks`` is populated for acknowledgement and ai_disclosure; it is
    empty (and ignored) for generated pages like title_page and certificate.
    """

    kind: Literal[
        "title_page",
        "certificate",
        "declaration",
        "acknowledgement",
        "ai_disclosure",
        "contents",
        "abbreviations",
    ]
    body_blocks: list[Block] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Metadata sub-models
# ---------------------------------------------------------------------------


class CandidateMeta(BaseModel):
    """Candidate (student) identifying information for front-matter pages."""

    name: str = ""
    reg_no: str = ""


class CollegeMeta(BaseModel):
    """College / institution information for front-matter pages.

    ``logo_key`` is an R2 object key (or local relative path in dev) for the
    college logo image displayed on the title page.
    """

    name: str = ""
    affiliation: str = ""
    city: str = ""
    pin: str = ""
    logo_key: str = ""


class PersonMeta(BaseModel):
    """A named academic (guide or HoD) with designation."""

    name: str = ""
    designation: str = ""


class SubmissionMeta(BaseModel):
    """Month and year of submission printed on the title page."""

    month: str = ""
    year: int | None = None


class AiDisclosure(BaseModel):
    """Controls the optional AI-Assistance Disclosure front-matter page."""

    enabled: bool = False
    text: str = ""


class ThesisMeta(BaseModel):
    """Complete metadata block for a thesis project.

    All sub-models default to empty instances so that ``ThesisMeta()``
    and ``ThesisMeta.model_validate({})`` succeed — important because the
    Project.meta column defaults to ``{}``.
    """

    doc_type: Literal[
        "ma_dissertation",
        "mphil_dissertation",
        "phd_thesis",
        "project_report",
        "research_paper",
    ] = "ma_dissertation"
    title: str = ""
    candidate: CandidateMeta = Field(default_factory=CandidateMeta)
    degree: str = "Master of Arts in English"
    department: str = "Department of English"
    college: CollegeMeta = Field(default_factory=CollegeMeta)
    guide: PersonMeta = Field(default_factory=PersonMeta)
    hod: PersonMeta = Field(default_factory=PersonMeta)
    submission: SubmissionMeta = Field(default_factory=SubmissionMeta)
    ai_disclosure: AiDisclosure = Field(default_factory=AiDisclosure)


# ---------------------------------------------------------------------------
# Works Cited reference (pointer into the Citation Registry)
# ---------------------------------------------------------------------------


class WorksCitedRef(BaseModel):
    """A pointer to a source in the Citation Registry.

    Works Cited is *generated* from these pointers; hand-typed entries do not
    exist in Mode A.  The renderer calls ``works_cited.format_entry`` for each.
    """

    source_id: UUID


# ---------------------------------------------------------------------------
# Top-level document
# ---------------------------------------------------------------------------


class ThesisDocument(BaseModel):
    """The single canonical representation consumed by all renderers.

    ``style_profile_id`` points to a StyleProfile row (FORMAT_SPEC §8); when
    None the renderer uses the base profile named by ``meta.doc_type`` +
    ``Project.format_profile``.
    """

    meta: ThesisMeta = Field(default_factory=ThesisMeta)
    style_profile_id: UUID | None = None
    front_matter: list[FrontMatterEntry] = Field(default_factory=list)
    chapters: list[ChapterDoc] = Field(default_factory=list)
    works_cited: list[WorksCitedRef] = Field(default_factory=list)


# Rebuild all models so forward references in the discriminated union resolve
# correctly even under ``from __future__ import annotations``.
ParagraphBlock.model_rebuild()
BlockQuoteBlock.model_rebuild()
VerseQuoteBlock.model_rebuild()
HeadingBlock.model_rebuild()
MarkerBlock.model_rebuild()
ChapterDoc.model_rebuild()
FrontMatterEntry.model_rebuild()
ThesisDocument.model_rebuild()
