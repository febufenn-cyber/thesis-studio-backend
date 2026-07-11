"""Canonical ThesisDocument model — the single source of truth for all renderers.

Phase 1 correctness contract:
- every structural object has a stable UUID;
- imported blocks preserve their source paragraph/revision provenance;
- unresolved or unsupported content is explicit and export-blocking;
- older JSON remains readable because all new identity fields have defaults.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


CANONICAL_SCHEMA_VERSION = 2


class Run(BaseModel):
    """A contiguous span of text with optional italic emphasis."""

    text: str
    italic: bool = False


class BlockIdentity(BaseModel):
    """Stable identity and import provenance shared by all canonical blocks."""

    id: UUID = Field(default_factory=uuid4)
    source_revision_id: UUID | None = None
    source_paragraph_index: int | None = None


class ParagraphBlock(BlockIdentity):
    """A body paragraph composed of one or more styled runs."""

    type: Literal["paragraph"] = "paragraph"
    runs: list[Run]


class BlockQuoteBlock(BlockIdentity):
    """A prose quotation longer than four typed lines."""

    type: Literal["block_quote"] = "block_quote"
    text: str
    citation: str = ""
    quote_id: UUID | None = None


class VerseQuoteBlock(BlockIdentity):
    """A verse quotation whose original lineation is preserved."""

    type: Literal["verse_quote"] = "verse_quote"
    lines: list[str]
    citation: str = ""
    quote_id: UUID | None = None


class HeadingBlock(BlockIdentity):
    """A level-2 or level-3 heading inside a chapter."""

    type: Literal["heading"] = "heading"
    level: Literal[2, 3]
    text: str


class MarkerBlock(BlockIdentity):
    """An explicit unresolved item that blocks a final export.

    ``UNSUPPORTED`` is used when the original DOCX contains an object the
    canonical model cannot safely reconstruct. ``REVIEW_REQUIRED`` is used for
    low-confidence structural decisions. The original upload remains immutable,
    so no content is silently discarded.
    """

    type: Literal["marker"] = "marker"
    kind: Literal[
        "QUOTE_NEEDED",
        "VERIFY",
        "UNSUPPORTED",
        "REVIEW_REQUIRED",
    ]
    note: str
    evidence: dict = Field(default_factory=dict)


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


class ChapterDoc(BaseModel):
    """One chapter represented as an ordered list of stable blocks."""

    id: UUID = Field(default_factory=uuid4)
    number: int
    title: str
    status: Literal["draft", "review", "approved"] = "draft"
    blocks: list[Block] = Field(default_factory=list)


class FrontMatterEntry(BaseModel):
    """One front-matter section in canonical order."""

    id: UUID = Field(default_factory=uuid4)
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


class CandidateMeta(BaseModel):
    name: str = ""
    reg_no: str = ""


class CollegeMeta(BaseModel):
    name: str = ""
    affiliation: str = ""
    city: str = ""
    pin: str = ""
    logo_key: str = ""


class PersonMeta(BaseModel):
    name: str = ""
    designation: str = ""


class SubmissionMeta(BaseModel):
    month: str = ""
    year: int | None = None


class AiDisclosure(BaseModel):
    enabled: bool = False
    text: str = ""


class ThesisMeta(BaseModel):
    """Complete metadata block for a thesis project.

    Fields remain optional while drafting. The export gate applies the selected
    profile's required-field policy before rendering.
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


class WorksCitedRef(BaseModel):
    source_id: UUID


class ThesisDocument(BaseModel):
    """The canonical representation consumed by every renderer."""

    schema_version: int = CANONICAL_SCHEMA_VERSION
    meta: ThesisMeta = Field(default_factory=ThesisMeta)
    style_profile_id: UUID | None = None
    front_matter: list[FrontMatterEntry] = Field(default_factory=list)
    chapters: list[ChapterDoc] = Field(default_factory=list)
    works_cited: list[WorksCitedRef] = Field(default_factory=list)


ParagraphBlock.model_rebuild()
BlockQuoteBlock.model_rebuild()
VerseQuoteBlock.model_rebuild()
HeadingBlock.model_rebuild()
MarkerBlock.model_rebuild()
ChapterDoc.model_rebuild()
FrontMatterEntry.model_rebuild()
ThesisDocument.model_rebuild()
