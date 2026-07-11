"""Citation extraction and deterministic resolution.

Bibliographic data is never guessed. Missing required values become [VERIFY].
Citation resolution uses a conservative ladder and never auto-links an
ambiguous surname to multiple registry sources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.canonical.model import BlockQuoteBlock, ParagraphBlock, Run, ThesisDocument, VerseQuoteBlock


VERIFY = "[VERIFY]"
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
    block_id: str = ""
    block_index: int = 0
    raw: str = ""


@dataclass
class SourceCandidate:
    kind: str
    fields: dict = field(default_factory=dict)
    verify_note: str = ""
    raw_entry: str = ""
    source_paragraph_index: int | None = None
    parser_confidence: float = 0.0
    parse_status: str = "structured_with_review"
    identifiers: dict = field(default_factory=dict)


def scan_document(doc: ThesisDocument) -> list[InTextCitation]:
    found: list[InTextCitation] = []
    for chapter in doc.chapters:
        for index, block in enumerate(chapter.blocks):
            if isinstance(block, ParagraphBlock):
                text = "".join(run.text for run in block.runs)
            elif isinstance(block, (BlockQuoteBlock, VerseQuoteBlock)):
                text = f"({block.citation})" if block.citation else ""
            else:
                continue
            for match in _INTEXT_RE.finditer(text):
                found.append(
                    InTextCitation(
                        surname=match.group("name").split()[0].rstrip(",").strip(),
                        pages=(match.group("pages") or "").replace(" ", ""),
                        title_hint=(match.group("title") or "").strip(),
                        qtd_in=bool(match.group("qtd")),
                        chapter=chapter.number,
                        block_id=str(block.id),
                        block_index=index,
                        raw=match.group(0),
                    )
                )
    return found


def _first_sentence_segments(text: str) -> list[str]:
    protected = re.sub(r"\b([A-Z])\.\s", r"\1<DOT> ", text)
    parts = [segment.strip() for segment in protected.split(". ") if segment.strip()]
    return [part.replace("<DOT> ", ". ").rstrip(".") for part in parts]


def _finish(candidate: SourceCandidate) -> SourceCandidate:
    values = [str(value) for value in candidate.fields.values()]
    missing = sum(1 for value in values if not value.strip() or VERIFY in value)
    candidate.parser_confidence = round(max(0.05, 1 - (missing / max(len(values), 1))), 2)
    candidate.parse_status = "fully_structured" if missing == 0 else "structured_with_review"
    return candidate


def parse_wc_entry(runs: list[Run], paragraph_index: int | None = None) -> SourceCandidate:
    text = "".join(run.text for run in runs).strip()
    italic_texts = [run.text.strip().rstrip(".,") for run in runs if run.italic and run.text.strip()]
    italic_main = italic_texts[0] if italic_texts else ""
    quoted = _QUOTED_RE.search(text)
    year_match = _YEAR_RE.search(text)
    pages_match = _PAGES_RE.search(text)
    url_match = _URL_RE.search(text)
    lower = text.lower()

    author = ""
    segments = _first_sentence_segments(text)
    if segments:
        head = segments[0]
        if head.startswith("---"):
            author = VERIFY
        elif "," in head and not head.startswith(("“", '"')) and head != italic_main:
            author = head

    def missing(note: str) -> str:
        return f"Could not read: {note}. Confirm against the original source."

    year = year_match.group(0) if year_match else VERIFY
    identifiers: dict[str, str] = {}
    if url_match:
        raw_url = url_match.group(0).rstrip(".")
        identifiers["doi_or_url"] = raw_url

    common = {
        "raw_entry": text,
        "source_paragraph_index": paragraph_index,
        "identifiers": identifiers,
    }

    if "directed by" in lower:
        director = re.search(r"directed by\s+([^,.]+)", text, re.IGNORECASE)
        studio_segment = segments[-1] if segments else ""
        studio = studio_segment.split(",")[-2].strip() if studio_segment.count(",") >= 1 else VERIFY
        return _finish(
            SourceCandidate(
                kind="film",
                fields={
                    "title": italic_main or VERIFY,
                    "director": director.group(1).strip() if director else VERIFY,
                    "studio": studio,
                    "year": year,
                },
                verify_note="" if italic_main and director else missing("film credits"),
                **common,
            )
        )

    if quoted and (_VOL_RE.search(text) or _NO_RE.search(text)):
        fields = {
            "author": author or VERIFY,
            "title": quoted.group("t").rstrip("."),
            "container": italic_main or VERIFY,
            "volume": _VOL_RE.search(text).group(1) if _VOL_RE.search(text) else VERIFY,
            "number": _NO_RE.search(text).group(1) if _NO_RE.search(text) else VERIFY,
            "year": year,
            "pages": pages_match.group(1) if pages_match else VERIFY,
        }
        kind = "journal"
        if url_match or len(italic_texts) > 1:
            kind = "journal_db"
            fields["database"] = italic_texts[1] if len(italic_texts) > 1 else VERIFY
            fields["doi_or_url"] = url_match.group(0).rstrip(".") if url_match else VERIFY
        return _finish(
            SourceCandidate(
                kind=kind,
                fields=fields,
                verify_note="" if VERIFY not in fields.values() else missing("journal fields"),
                **common,
            )
        )

    if quoted and "edited by" in lower:
        editor = re.search(r"edited by\s+([^,]+)", text, re.IGNORECASE)
        publisher_match = re.search(
            r"edited by\s+[^,]+,\s*([^,]+),\s*(1[5-9]\d{2}|20\d{2})",
            text,
            re.IGNORECASE,
        )
        return _finish(
            SourceCandidate(
                kind="chapter_in_collection",
                fields={
                    "author": author or VERIFY,
                    "title": quoted.group("t").rstrip("."),
                    "container": italic_main or VERIFY,
                    "editor": editor.group(1).strip() if editor else VERIFY,
                    "publisher": publisher_match.group(1).strip() if publisher_match else VERIFY,
                    "year": year,
                    "pages": pages_match.group(1) if pages_match else VERIFY,
                },
                verify_note="" if publisher_match else missing("collection publisher"),
                **common,
            )
        )

    if quoted and (url_match or (italic_main and not pages_match)):
        return _finish(
            SourceCandidate(
                kind="web",
                fields={
                    "author": author,
                    "title": quoted.group("t").rstrip("."),
                    "site": italic_main or VERIFY,
                    "url": url_match.group(0).rstrip(".") if url_match else VERIFY,
                },
                verify_note="" if url_match else missing("URL"),
                **common,
            )
        )

    translator_match = re.search(r"translated by\s+([^,]+)", text, re.IGNORECASE)
    publisher = VERIFY
    publisher_match = re.search(
        r"(?:^|\.)\s*([^.,]{2,60}?),\s*(1[5-9]\d{2}|20\d{2})\.?\s*$", text
    )
    if publisher_match:
        publisher = publisher_match.group(1).strip()
        if translator_match and publisher.lower().startswith("translated by"):
            publisher = VERIFY
    fields = {
        "author": author or VERIFY,
        "title": italic_main or VERIFY,
        "publisher": publisher,
        "year": year,
    }
    kind = "book"
    if translator_match:
        kind = "translated_book"
        fields["translator"] = translator_match.group(1).strip()
    return _finish(
        SourceCandidate(
            kind=kind,
            fields=fields,
            verify_note="" if VERIFY not in fields.values() else missing("book imprint fields"),
            **common,
        )
    )


def parse_wc_entries(raw_entries: list[Any]) -> list[SourceCandidate]:
    """Parse entries while preserving source paragraph indexes.

    Accepts both legacy ``list[list[Run]]`` and Phase 1
    ``list[tuple[paragraph_index, list[Run]]]`` inputs.
    """

    output: list[SourceCandidate] = []
    previous_author = ""
    for entry in raw_entries:
        if isinstance(entry, tuple):
            paragraph_index, runs = entry
        else:
            paragraph_index, runs = None, entry
        candidate = parse_wc_entry(runs, paragraph_index)
        if candidate.fields.get("author") == VERIFY and candidate.raw_entry.startswith("---"):
            if previous_author:
                candidate.fields["author"] = previous_author
                candidate.verify_note = candidate.verify_note or "Repeated author inherited; confirm entry."
                candidate.parse_status = "structured_with_review"
            else:
                candidate.verify_note = "Entry begins with '---.' but no prior author can be inherited."
        if candidate.fields.get("author") and candidate.fields["author"] != VERIFY:
            previous_author = candidate.fields["author"]
        output.append(candidate)
    return output


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def resolve_citation(
    citation: InTextCitation,
    sources: dict[UUID, Any],
) -> tuple[UUID | None, list[UUID], str]:
    """Resolve conservatively: title hint first, then unique surname.

    Returns ``(resolved_id, candidates, reason)``. An ambiguous result never
    chooses a source automatically.
    """

    surname = citation.surname.lower()
    matches = [
        source_id
        for source_id, source in sources.items()
        if str(source.fields.get("author", "")).split(",")[0].strip().lower() == surname
    ]
    if not matches:
        return None, [], "no_surname_match"
    if citation.title_hint:
        hint = _normalise(citation.title_hint)
        title_matches = [
            source_id
            for source_id in matches
            if hint and hint in _normalise(str(sources[source_id].fields.get("title", "")))
        ]
        if len(title_matches) == 1:
            return title_matches[0], title_matches, "surname_and_title"
        if len(title_matches) > 1:
            return None, title_matches, "ambiguous_title_match"
    if len(matches) == 1:
        return matches[0], matches, "unique_surname"
    return None, matches, "ambiguous_surname"
