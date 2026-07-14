"""Extractor protocol and the extracted-document shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = ["PageText", "ExtractedDoc", "ExtractorError", "SourceTextExtractor"]


class ExtractorError(RuntimeError):
    """Raised when a source cannot be read; maps to status 'unverifiable'."""


@dataclass(frozen=True)
class PageText:
    locator: str
    text: str


@dataclass(frozen=True)
class ExtractedDoc:
    pages: list[PageText] = field(default_factory=list)
    extractor: str = ""

    @property
    def full_text(self) -> str:
        return "\n".join(page.text for page in self.pages)


@runtime_checkable
class SourceTextExtractor(Protocol):
    mime_types: tuple[str, ...]

    def extract(self, data: bytes) -> ExtractedDoc: ...
