"""Canonical ThesisDocument model — the single source of truth for all renderers.

Phase 2 extends the Phase 1 correctness contract:
- every structural object keeps a stable UUID and import provenance;
- chapter/front-matter review state is explicit and dependency-aware;
- old v2 JSON remains readable while project rows track schema version 3;
- presentation remains profile-driven and never mutates author text.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union, get_args
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


CANONICAL_SCHEMA_VERSION = 3

# Authorship of a structural block. ``None`` means the origin is unknown — a
# legacy block written before origin tracking existed. The BlockIdentity
# validator below back-fills manuscript-imported blocks from their import
# provenance so legacy documents still attribute correctly.
BlockOrigin = Literal["manuscript_import", "human", "ai_proposal"]

# Single source of truth for editorial marker kinds. Both the canonical model
# (``MarkerBlock.kind``) and the AI proposal validator
# (``app/ai/proposal_engine._ALLOWED_MARKERS``) derive from this set, so the two
# can never drift apart and let a human-accepted proposal carry a marker kind
# that then crashes when the MarkerBlock is constructed at apply time.
MarkerKind = Literal[
    "QUOTE_NEEDED",
    "VERIFY",
    "SOURCE_NEEDED",
    "UNSUPPORTED",
    "REVIEW_REQUIRED",
    "STRUCTURE_REVIEW",
    "EVIDENCE_NEEDED",
]
MARKER_KINDS: frozenset[str] = frozenset(get_args(MarkerKind))
ReviewStatus = Literal[
    "imported",
    "needs_review",
    "in_progress",
    "reviewed",
    "approved",
    "locked",
    # Phase 1 compatibility aliases. New commands normalise these values.
    "draft",
    "review",
]


class Run(BaseModel):
    text: str
    italic: bool = False


class BlockIdentity(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_revision_id: UUID | None = None
    source_paragraph_index: int | None = None
    origin: BlockOrigin | None = None

    @model_validator(mode="after")
    def _infer_origin(self) -> BlockIdentity:
        # Blocks imported before origin tracking carry manuscript provenance but
        # no explicit origin; treat those as manuscript-imported. Blocks authored
        # by a human editor or an AI proposal set ``origin`` explicitly and are
        # left untouched here.
        if self.origin is None and self.source_revision_id is not None:
            self.origin = "manuscript_import"
        return self


class ParagraphBlock(BlockIdentity):
    type: Literal["paragraph"] = "paragraph"
    runs: list[Run]


class BlockQuoteBlock(BlockIdentity):
    type: Literal["block_quote"] = "block_quote"
    text: str
    citation: str = ""
    quote_id: UUID | None = None


class VerseQuoteBlock(BlockIdentity):
    type: Literal["verse_quote"] = "verse_quote"
    lines: list[str]
    citation: str = ""
    quote_id: UUID | None = None


class HeadingBlock(BlockIdentity):
    type: Literal["heading"] = "heading"
    level: Literal[2, 3]
    text: str


class MarkerBlock(BlockIdentity):
    """Explicit unresolved item; all marker kinds block a final export."""

    type: Literal["marker"] = "marker"
    kind: MarkerKind
    note: str
    evidence: dict = Field(default_factory=dict)


Block = Annotated[
    Union[ParagraphBlock, BlockQuoteBlock, VerseQuoteBlock, HeadingBlock, MarkerBlock],
    Field(discriminator="type"),
]


class ChapterDoc(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_revision_id: UUID | None = None
    source_paragraph_index: int | None = None
    title_source_paragraph_index: int | None = None
    number: int
    title: str
    status: ReviewStatus = "imported"
    blocks: list[Block] = Field(default_factory=list)


class FrontMatterEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_revision_id: UUID | None = None
    source_paragraph_index: int | None = None
    kind: Literal[
        "title_page",
        "certificate",
        "declaration",
        "acknowledgement",
        "ai_disclosure",
        "contents",
        "abbreviations",
    ]
    status: ReviewStatus = "imported"
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
    tools: list[str] = Field(default_factory=list)
    assistance_types: list[str] = Field(default_factory=list)


class ThesisMeta(BaseModel):
    """Metadata may be incomplete during editing; export validation is strict."""

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
    # Citation style key (see app/renderers/styles). Default MLA keeps existing
    # documents and output byte-for-byte identical.
    citation_style: str = "mla-9"
    # Domain-profile key that seeded this document (see app/domains/profiles).
    # Empty string means no profile was declared at creation.
    domain_profile: str = ""


class WorksCitedRef(BaseModel):
    source_id: UUID


class ThesisDocument(BaseModel):
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
