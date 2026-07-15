"""JATS XML export — rendered directly from the canonical ThesisDocument.

JATS (Journal Article Tag Suite) is the journal-submission interchange standard.
Like the other renderers this walks the canonical document directly and never
invents bibliographic data (absent fields are skipped). An unresolved
``MarkerBlock`` aborts export (``RenderError``), mirroring the final-export rule.
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

from app.canonical.model import (
    BlockQuoteBlock,
    HeadingBlock,
    MarkerBlock,
    ParagraphBlock,
    Run,
    ThesisDocument,
    VerseQuoteBlock,
)
from app.renderers.docx_renderer import RenderError
from app.renderers.works_cited import SourceLike


def _esc(text: Any) -> str:
    return escape(str(text or ""))


def _runs_jats(runs: list[Run]) -> str:
    parts: list[str] = []
    for r in runs or []:
        body = _esc(r.text)
        parts.append(f"<italic>{body}</italic>" if r.italic else body)
    return "".join(parts)


def _block_jats(block: Any) -> str:
    if isinstance(block, ParagraphBlock):
        return f"<p>{_runs_jats(block.runs)}</p>"
    if isinstance(block, BlockQuoteBlock):
        body = f"<p>{_esc(block.text)}</p>"
        if block.citation:
            body += f"<attrib>{_esc(block.citation)}</attrib>"
        return f"<disp-quote>{body}</disp-quote>"
    if isinstance(block, VerseQuoteBlock):
        lines = "".join(f"<verse-line>{_esc(line)}</verse-line>" for line in (block.lines or []))
        if block.citation:
            lines += f"<attrib>{_esc(block.citation)}</attrib>"
        return f"<verse-group>{lines}</verse-group>"
    if isinstance(block, HeadingBlock):
        return f"<sec><title>{_esc(block.text)}</title></sec>"
    if isinstance(block, MarkerBlock):
        raise RenderError(
            f"Unresolved marker [{block.kind}] cannot be exported to JATS: {block.note}"
        )
    return ""


def _ref_list(doc: ThesisDocument, sources: dict[Any, SourceLike]) -> str:
    refs: list[str] = []
    for i, ref in enumerate(doc.works_cited, start=1):
        src = sources.get(ref.source_id) or sources.get(str(ref.source_id))
        if src is None:
            continue
        fields = getattr(src, "fields", {}) or {}
        parts: list[str] = []
        author = str(fields.get("author", "")).strip()
        if author:
            parts.append(f"<person-group person-group-type='author'><string-name>{_esc(author)}</string-name></person-group>")
        title = str(fields.get("title", "")).strip()
        if title:
            parts.append(f"<article-title>{_esc(title)}</article-title>")
        container = str(fields.get("container", "")).strip()
        if container:
            parts.append(f"<source>{_esc(container)}</source>")
        year = str(fields.get("year", "")).strip()
        if year:
            parts.append(f"<year>{_esc(year)}</year>")
        volume = str(fields.get("volume", "")).strip()
        if volume:
            parts.append(f"<volume>{_esc(volume)}</volume>")
        pages = str(fields.get("pages", "")).strip()
        if pages:
            parts.append(f"<fpage>{_esc(pages)}</fpage>")
        doi = str(fields.get("doi_or_url", "")).strip()
        if doi and "[VERIFY]" not in doi:
            parts.append(f"<pub-id pub-id-type='doi'>{_esc(doi)}</pub-id>")
        refs.append(
            f"<ref id='r{i}'><element-citation>{''.join(parts)}</element-citation></ref>"
        )
    if not refs:
        return ""
    return "<ref-list>" + "".join(refs) + "</ref-list>"


def to_jats(doc: ThesisDocument, sources: dict[Any, SourceLike]) -> str:
    """Render the canonical document to a JATS XML string."""
    meta = doc.meta
    title = _esc(getattr(meta, "title", "") or "")
    author = ""
    candidate = getattr(meta, "candidate", None)
    if candidate is not None:
        author = _esc(getattr(candidate, "name", "") or "")

    front = (
        "<front><article-meta>"
        f"<title-group><article-title>{title}</article-title></title-group>"
        f"<contrib-group><contrib contrib-type='author'><string-name>{author}</string-name></contrib></contrib-group>"
        "</article-meta></front>"
    )

    body_parts: list[str] = []
    for ch in doc.chapters:
        blocks = "".join(_block_jats(b) for b in ch.blocks)
        body_parts.append(f"<sec><title>{_esc(ch.title)}</title>{blocks}</sec>")
    body = "<body>" + "".join(body_parts) + "</body>"

    back = _ref_list(doc, sources)
    back_xml = f"<back>{back}</back>" if back else ""

    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<article xmlns:xlink='http://www.w3.org/1999/xlink' article-type='research-article'>"
        f"{front}{body}{back_xml}</article>"
    )


__all__ = ["to_jats"]
