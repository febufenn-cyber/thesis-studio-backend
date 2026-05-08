"""Thesis document generation pipeline. See SKILL.md for format spec."""

from app.formatter.thesis_formatter import (
    BlockQuotation,
    Chapter,
    FrontMatter,
    Section,
    SubSection,
    ThesisInput,
    render_thesis_docx,
)
from app.formatter.prompts import (
    COMPILE_SYSTEM_PROMPT,
    build_coaching_system_blocks,
)

__all__ = [
    "BlockQuotation",
    "Chapter",
    "FrontMatter",
    "Section",
    "SubSection",
    "ThesisInput",
    "render_thesis_docx",
    "COMPILE_SYSTEM_PROMPT",
    "build_coaching_system_blocks",
]
