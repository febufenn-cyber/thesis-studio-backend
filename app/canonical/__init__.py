"""Canonical Pydantic model for ThesisDocument.

All four renderers (docx, pdf, md, txt) consume this model as their sole
source of truth.  Import from here — never from the sub-module directly.
"""

from __future__ import annotations

from app.canonical.model import (
    AiDisclosure,
    Block,
    BlockQuoteBlock,
    CandidateMeta,
    ChapterDoc,
    CollegeMeta,
    FrontMatterEntry,
    HeadingBlock,
    MarkerBlock,
    ParagraphBlock,
    PersonMeta,
    Run,
    SubmissionMeta,
    ThesisDocument,
    ThesisMeta,
    VerseQuoteBlock,
    WorksCitedRef,
)

__all__ = [
    "AiDisclosure",
    "Block",
    "BlockQuoteBlock",
    "CandidateMeta",
    "ChapterDoc",
    "CollegeMeta",
    "FrontMatterEntry",
    "HeadingBlock",
    "MarkerBlock",
    "ParagraphBlock",
    "PersonMeta",
    "Run",
    "SubmissionMeta",
    "ThesisDocument",
    "ThesisMeta",
    "VerseQuoteBlock",
    "WorksCitedRef",
]
