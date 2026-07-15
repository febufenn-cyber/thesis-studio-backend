"""MIME → extractor dispatch."""

from __future__ import annotations

from app.verification.extractors.base import ExtractorError, SourceTextExtractor
from app.verification.extractors.pdf import PdfExtractor
from app.verification.extractors.text import HtmlExtractor, PlainTextExtractor

_EXTRACTORS: tuple[SourceTextExtractor, ...] = (
    PlainTextExtractor(),
    HtmlExtractor(),
    PdfExtractor(),
)


def get_extractor(mime_type: str) -> SourceTextExtractor:
    """Return the extractor for a MIME type, or raise ExtractorError."""
    normalized = (mime_type or "").split(";")[0].strip().lower()
    for extractor in _EXTRACTORS:
        if normalized in extractor.mime_types:
            return extractor
    raise ExtractorError(f"no extractor for MIME type: {mime_type!r}")
