"""PDF source extractor (optional pypdf dependency, guarded).

pypdf is imported lazily so the rest of verification works without it. If it is
unavailable or the PDF is unreadable, extraction raises ``ExtractorError`` and
the caller records ``unverifiable`` — never a false ``verified``.
"""

from __future__ import annotations

import io

from app.verification.extractors.base import ExtractedDoc, ExtractorError, PageText


class PdfExtractor:
    mime_types = ("application/pdf",)

    def extract(self, data: bytes) -> ExtractedDoc:
        try:
            from pypdf import PdfReader
        except Exception as exc:  # pragma: no cover - depends on environment
            raise ExtractorError("PDF extraction is unavailable (pypdf not installed)") from exc
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [
                PageText(locator=str(i + 1), text=(page.extract_text() or ""))
                for i, page in enumerate(reader.pages)
            ]
        except Exception as exc:
            raise ExtractorError(f"unreadable PDF: {exc}") from exc
        if not any(p.text.strip() for p in pages):
            raise ExtractorError("no extractable text in PDF")
        return ExtractedDoc(pages=pages, extractor="pypdf")
