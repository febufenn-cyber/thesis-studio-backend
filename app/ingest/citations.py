"""Citation extraction — in-text scans and Works Cited entry structuring.

Never guesses bibliographic data: any field a template needs that cannot be
read from the entry becomes the literal string "[VERIFY]" and the candidate
ships verified=False (GLOBAL_PREAMBLE rules 2–3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.canonical.model import (
    BlockQuoteBlock,
    ParagraphBlock,
    Run,
    ThesisDocument,
    VerseQuoteBlock,
)

VERIFY = "[VERIFY]"

# (Surname 45) · (Gilbert and Gubar 45) · (Greenblatt et al. 12)
# (Said, Orientalism 49) · (qtd. in Surname 88) · (Surname) — web, no page
_INTEXT_RE = re.compile(
    r"\((?P<qtd>qtd\.\s+in\s+)?"
    r"(?P<name>[A-Z][\w'’\-]+(?:\s+(?:and\s+[A-Z][\w'’\-]+|et\s+al\.))?)"
    r"(?:,\s*(?P<title>[^)\d][^)]*?))?"
    r"(?:\s+(?P<pages>\d+(?:\s*[-–]\s*\d+)?))?\)"
)
_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
_PAGES_RE = re.compile(r"pp?\.\s*([\dxvi]+(?:\s*[-–]\s*[\dxvi]+)?)", re.IGNORECASE)
_VOL_RE = re.compile(r"vol\.\s*(\d+)", re.IGNORECASE)
_NO_RE = re.compile(r"no\.\s*(\d+)", re.IGNORECASE)
_URL_RE = re.compile(r"(https?://\S+|www\.\S+|doi\.org/\S+)", re.IGNORECASE)
_QUOTED_RE = re.compile(r"[“\"](?P<t>[^”\"]+)[”\"]")


@dataclass
class InTextCitation:
    surname: str
    pages: str
    title_hint: str = ""
    qtd_in: bool = False
    chapter: int = 0
    block_index: int = 0
    raw: str = ""


@dataclass
class SourceCandidate:
    """Registry-ready source (verified=False always; operator confirms)."""

    kind: str
    fields: dict = field(default_factory=dict)
    verify_note: str = ""
    raw_entry: str = ""


def scan_document(doc: ThesisDocument) -> list[InTextCitation]:
    """Collect every parenthetical citation in body paragraphs and quotes."""
    found: list[InTextCitation] = []
    for ch in doc.chapters:
        for bi, block in enumerate(ch.blocks):
            if isinstance(block, ParagraphBlock):
                text = "".join(r.text for r in block.runs)
            elif isinstance(block, (BlockQuoteBlock, VerseQuoteBlock)):
                text = block.citation
                if text and not _INTEXT_RE.search(f"({text})"):
                    # citation field like "Dangarembga 112" without parens
                    text = f"({text})"
                else:
                    text = f"({block.citation})" if block.citation else ""
            else:
                continue
            for m in _INTEXT_RE.finditer(text):
                found.append(InTextCitation(
                    surname=m.group("name").split()[0].rstrip(",").strip(),
                    pages=(m.group("pages") or "").replace(" ", ""),
                    title_hint=(m.group("title") or "").strip(),
                    qtd_in=bool(m.group("qtd")),
                    chapter=ch.number,
                    block_index=bi,
                    raw=m.group(0),
                ))
    return found


def _first_sentence_segments(text: str) -> list[str]:
    """Split a WC entry on '. ' boundaries, protecting initials ('Said, E. W.')."""
    protected = re.sub(r"\b([A-Z])\.\s", r"\1<DOT> ", text)
    parts = [s.strip() for s in protected.split(". ") if s.strip()]
    return [p.replace("<DOT> ", ". ").rstrip(".") for p in parts]


def parse_wc_entry(runs: list[Run]) -> SourceCandidate:
    """Structure one Works Cited entry using text + italics (kind inference).

    Italic segments mark volume-level titles (book/journal/site/film), which
    is what makes deterministic MLA parsing possible.
    """
    text = "".join(r.text for r in runs).strip()
    italic_texts = [r.text.strip().rstrip(".,") for r in runs if r.italic and r.text.strip()]
    italic_main = italic_texts[0] if italic_texts else ""
    quoted = _QUOTED_RE.search(text)
    year_m = _YEAR_RE.search(text)
    pages_m = _PAGES_RE.search(text)
    url_m = _URL_RE.search(text)
    lower = text.lower()

    # Author: leading "Surname, First" before the first period — never italic,
    # never the quoted title. "---." repeats are surfaced for the operator.
    author = ""
    segs = _first_sentence_segments(text)
    if segs:
        head = segs[0]
        if head.startswith("---"):
            author = VERIFY  # same-author repeat; operator resolves from prior entry
        elif "," in head and not head.startswith(("“", '"')) and head != italic_main:
            author = head

    def missing(note: str) -> str:
        return f"Could not read: {note}. Confirm against MLA Bibliography/JSTOR."

    year = year_m.group(0) if year_m else VERIFY

    if "directed by" in lower:
        d = re.search(r"directed by\s+([^,.]+)", text, re.IGNORECASE)
        studio_seg = segs[-1] if segs else ""
        studio = studio_seg.split(",")[-2].strip() if studio_seg.count(",") >= 1 else VERIFY
        return SourceCandidate(
            kind="film",
            fields={"title": italic_main or VERIFY,
                    "director": d.group(1).strip() if d else VERIFY,
                    "studio": studio, "year": year},
            verify_note="" if italic_main and d else missing("film credits"),
            raw_entry=text,
        )

    if quoted and (_VOL_RE.search(text) or _NO_RE.search(text)):
        fields = {
            "author": author or VERIFY,
            "title": quoted.group("t").rstrip("."),
            "container": italic_main or VERIFY,
            "volume": (_VOL_RE.search(text) or [None, VERIFY])[1],
            "number": (_NO_RE.search(text) or [None, VERIFY])[1],
            "year": year,
            "pages": pages_m.group(1) if pages_m else VERIFY,
        }
        if url_m or (len(italic_texts) > 1):
            fields["database"] = italic_texts[1] if len(italic_texts) > 1 else VERIFY
            fields["doi_or_url"] = url_m.group(0).rstrip(".") if url_m else VERIFY
            kind = "journal_db"
        else:
            kind = "journal"
        note = "" if VERIFY not in fields.values() else missing("journal fields")
        return SourceCandidate(kind=kind, fields=fields, verify_note=note, raw_entry=text)

    if quoted and "edited by" in lower:
        ed = re.search(r"edited by\s+([^,]+)", text, re.IGNORECASE)
        pub_year_seg = segs[-1] if segs else ""
        publisher = VERIFY
        pm = re.search(r"edited by\s+[^,]+,\s*([^,]+),\s*(1[5-9]\d{2}|20\d{2})", text, re.IGNORECASE)
        if pm:
            publisher = pm.group(1).strip()
        return SourceCandidate(
            kind="chapter_in_collection",
            fields={"author": author or VERIFY,
                    "title": quoted.group("t").rstrip("."),
                    "container": italic_main or VERIFY,
                    "editor": ed.group(1).strip() if ed else VERIFY,
                    "publisher": publisher, "year": year,
                    "pages": pages_m.group(1) if pages_m else VERIFY},
            verify_note="" if pm else missing("collection publisher"),
            raw_entry=text,
        )

    if quoted and (url_m or (italic_main and not pages_m)):
        return SourceCandidate(
            kind="web",
            fields={"author": author,
                    "title": quoted.group("t").rstrip("."),
                    "site": italic_main or VERIFY,
                    "url": url_m.group(0).rstrip(".") if url_m else VERIFY},
            verify_note="" if url_m else missing("URL"),
            raw_entry=text,
        )

    # Book family (default): translated when "Translated by" appears.
    translator_m = re.search(r"translated by\s+([^,]+)", text, re.IGNORECASE)
    publisher = VERIFY
    pub_m = re.search(
        r"(?:^|\.)\s*([^.,]{2,60}?),\s*(1[5-9]\d{2}|20\d{2})\.?\s*$", text
    )
    if pub_m:
        publisher = pub_m.group(1).strip()
        if translator_m and publisher.lower().startswith("translated by"):
            publisher = VERIFY
    fields = {
        "author": author or VERIFY,
        "title": italic_main or VERIFY,
        "publisher": publisher,
        "year": year,
    }
    kind = "book"
    if translator_m:
        kind = "translated_book"
        fields["translator"] = translator_m.group(1).strip()
    note = "" if VERIFY not in fields.values() else missing("book imprint fields")
    return SourceCandidate(kind=kind, fields=fields, verify_note=note, raw_entry=text)


def parse_wc_entries(raw_entries: list[list[Run]]) -> list[SourceCandidate]:
    """Structure the whole Works Cited section, resolving '---.' repeats."""
    out: list[SourceCandidate] = []
    prev_author = ""
    for runs in raw_entries:
        cand = parse_wc_entry(runs)
        if cand.fields.get("author") == VERIFY and cand.raw_entry.startswith("---"):
            if prev_author:
                cand.fields["author"] = prev_author
                cand.verify_note = cand.verify_note or ""
            else:
                cand.verify_note = "Entry begins with '---.' but no prior author to inherit."
        if cand.fields.get("author") and cand.fields["author"] != VERIFY:
            prev_author = cand.fields["author"]
        out.append(cand)
    return out
