"""Validator protocol and shared types for venue compliance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from app.canonical.model import ThesisDocument
    from app.domains.profiles import DomainProfile

Severity = Literal["block", "warn", "info"]


class UnknownValidator(KeyError):
    """The requested validator key is not registered."""


@dataclass(frozen=True)
class ValidationFinding:
    validator: str
    severity: Severity
    code: str
    message: str
    locator: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "validator": self.validator,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "locator": self.locator,
        }


@dataclass(frozen=True)
class PageInfo:
    """Measured/estimated page count for the compiled body."""

    page_count: int | None
    measured_by: str  # "pdf" | "estimate" | "unavailable"
    detail: str = ""


@dataclass(frozen=True)
class ComplianceContext:
    document: "ThesisDocument"
    profile: "DomainProfile"
    page_info: PageInfo
    reproducibility_answers: dict = field(default_factory=dict)
    present_sections: frozenset[str] = frozenset()


class ProfileValidator(Protocol):
    key: str

    def validate(self, context: ComplianceContext) -> list[ValidationFinding]: ...


def block_text_of(block) -> str:
    """Extract comparable text from any canonical block."""
    runs = getattr(block, "runs", None)
    if runs is not None:
        return " ".join(run.text for run in runs)
    text = getattr(block, "text", None)
    if text is not None:
        return str(text)
    lines = getattr(block, "lines", None)
    if lines is not None:
        return " ".join(lines)
    return ""


def iter_body_text(document: "ThesisDocument"):
    """Yield (locator, text) for every block in chapters and front matter."""
    for chapter in document.chapters:
        for block in chapter.blocks:
            yield {"chapter": str(chapter.id), "block_id": str(block.id)}, block_text_of(block)
    for entry in document.front_matter:
        for block in entry.body_blocks:
            yield {"front_matter": entry.kind, "block_id": str(block.id)}, block_text_of(block)
