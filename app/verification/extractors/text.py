"""Plain-text and HTML source extractors (stdlib only)."""

from __future__ import annotations

from html.parser import HTMLParser

from app.verification.extractors.base import ExtractedDoc, ExtractorError, PageText


class PlainTextExtractor:
    mime_types = ("text/plain",)

    def extract(self, data: bytes) -> ExtractedDoc:
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception as exc:  # pragma: no cover - decode is very tolerant
            raise ExtractorError(str(exc)) from exc
        if not text.strip():
            raise ExtractorError("empty source text")
        return ExtractedDoc(pages=[PageText(locator="1", text=text)], extractor="text")


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._chunks.append(data)

    @property
    def text(self) -> str:
        return " ".join(self._chunks)


class HtmlExtractor:
    mime_types = ("text/html", "application/xhtml+xml")

    def extract(self, data: bytes) -> ExtractedDoc:
        try:
            html = data.decode("utf-8", errors="replace")
            parser = _Stripper()
            parser.feed(html)
            text = parser.text
        except Exception as exc:
            raise ExtractorError(str(exc)) from exc
        if not text.strip():
            raise ExtractorError("no extractable text in HTML")
        return ExtractedDoc(pages=[PageText(locator="1", text=text)], extractor="html")
