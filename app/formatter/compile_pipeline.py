"""
compile_pipeline.py — End-to-end compile flow.

Takes a session's conversation history, calls Claude Opus with the COMPILE_SYSTEM_PROMPT,
parses the returned JSON into ThesisInput dataclasses, and renders the final .docx.

This is the function the FastAPI `/sessions/{id}/compile` endpoint calls.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.formatter.thesis_formatter import (
    FrontMatter, ThesisInput, Chapter, Section, SubSection, BlockQuotation,
    render_thesis_docx,
)
from app.formatter.prompts import COMPILE_SYSTEM_PROMPT

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.claude_service import ClaudeService


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON → dataclass parsers
# ---------------------------------------------------------------------------

def _parse_block_quotations(raw: list[dict[str, Any]]) -> list[tuple[int, BlockQuotation]]:
    """Parse JSON block quotations into the formatter's (index, BlockQuotation) tuples."""
    result = []
    for item in raw or []:
        idx = int(item.get('after_paragraph_index', 0))
        bq = BlockQuotation(
            text=item['text'],
            citation=item.get('citation', ''),
        )
        result.append((idx, bq))
    return result


def _parse_subsection(raw: dict[str, Any]) -> SubSection:
    return SubSection(
        number=raw['number'],
        heading=raw['heading'],
        paragraphs=raw.get('paragraphs', []),
        block_quotations=_parse_block_quotations(raw.get('block_quotations', [])),
    )


def _parse_section(raw: dict[str, Any]) -> Section:
    return Section(
        number=raw['number'],
        heading=raw['heading'],
        paragraphs=raw.get('paragraphs', []),
        block_quotations=_parse_block_quotations(raw.get('block_quotations', [])),
        subsections=[_parse_subsection(s) for s in raw.get('subsections', [])],
    )


def _parse_chapter(raw: dict[str, Any]) -> Chapter:
    return Chapter(
        number_roman=raw['number_roman'],
        title=raw['title'],
        intro_paragraphs=raw.get('intro_paragraphs', []),
        intro_block_quotations=_parse_block_quotations(raw.get('intro_block_quotations', [])),
        sections=[_parse_section(s) for s in raw.get('sections', [])],
    )


def parse_compile_json(raw_json: str | dict, front_matter: FrontMatter) -> ThesisInput:
    """Parse the JSON returned by the compile pass into a ThesisInput.

    Front matter (institution + student details) is injected from the session record,
    not from Claude's output, since the model wasn't responsible for that data.
    """
    if isinstance(raw_json, str):
        # Strip any code fences the model might have added despite instructions
        cleaned = raw_json.strip()
        if cleaned.startswith('```'):
            # Remove ```json and trailing ```
            cleaned = cleaned.split('\n', 1)[1]
            if cleaned.endswith('```'):
                cleaned = cleaned.rsplit('```', 1)[0]
        data = json.loads(cleaned)
    else:
        data = raw_json

    return ThesisInput(
        front_matter=front_matter,
        abstract=data.get('abstract', ''),
        keywords=data.get('keywords', []),
        acknowledgement=data.get('acknowledgement', ''),
        chapters=[_parse_chapter(c) for c in data.get('chapters', [])],
        works_cited=data.get('works_cited', []),
    )


# ---------------------------------------------------------------------------
# Main compile entry point
# ---------------------------------------------------------------------------

async def compile_thesis(
    *,
    claude_service: ClaudeService,
    db: AsyncSession,
    user_id: UUID,
    session_id: UUID,
    conversation_messages: list[dict[str, str]],
    front_matter: FrontMatter,
    logo_path: str,
    output_path: str,
    model: str = "claude-opus-4-7",
) -> str:
    """
    Run the full compile pipeline:
        1. Call Claude (via the CLI subprocess in ClaudeService) with the
           conversation + COMPILE_SYSTEM_PROMPT.
        2. Parse the JSON response.
        3. Render the .docx file.

    Args:
        claude_service: shared ClaudeService instance (manages the CLI subprocess).
        db, user_id, session_id: required so the call records a usage_events row.
        conversation_messages: full session history as [{"role": ..., "content": ...}, ...].
        front_matter: institution and student data from the session intake form.
        logo_path: path to the college logo image.
        output_path: where to write the .docx.
        model: which Claude model to use. Opus 4.7 recommended for compile coherence.

    Returns:
        output_path on success.
    """
    log.info("Calling Claude compile pass: model=%s, history_turns=%d",
             model, len(conversation_messages))

    raw_text = await claude_service.call_compile(
        messages=conversation_messages,
        system_prompt=COMPILE_SYSTEM_PROMPT,
        db=db,
        user_id=user_id,
        session_id=session_id,
        model=model,
    )

    log.info("Compile pass complete: response_chars=%d", len(raw_text))

    thesis_input = parse_compile_json(raw_text, front_matter)

    render_thesis_docx(
        thesis_input,
        logo_path=logo_path,
        output_path=output_path,
    )

    return output_path
