"""Frozen inline-quotation corpus + scorer. APPEND-ONLY after freeze.

Ground truth (never-guess): a quote counts as linkable ONLY when its
parenthetical citation resolves unambiguously. A bare surname shared by two
sources is CORRECTLY skipped — capturing it would be a fabricated link
(counts 10x worse than a miss). Short scare-quote fragments are noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class QCase:
    id: str
    paragraph: str
    # expected: list of (source_key, quote_substring, pages)
    expect: list = field(default_factory=list)
    # quotes that MUST NOT be linked (ambiguous / uncited / fragment)
    must_skip: list = field(default_factory=list)


# Registry for the corpus: key -> fields (author/title used by resolution).
SOURCES = {
    "remains": {"author": "Ishiguro, Kazuo", "title": "The Remains of the Day"},
    "neverlet": {"author": "Ishiguro, Kazuo", "title": "Never Let Me Go"},
    "ricoeur": {"author": "Ricoeur, Paul", "title": "Memory, History, Forgetting"},
    "phelan": {"author": "Phelan, James, and Mary Patricia Martin", "title": "The Lessons of Weymouth"},
    "booth": {"author": "Booth, Wayne C.", "title": "The Rhetoric of Fiction"},
    "nunning": {"author": "Nunning, Ansgar", "title": "Unreliable Narration Reconsidered"},
}

CASES: list[QCase] = [
    QCase("unique_surname_long",
          'Ricoeur argues that "memory is exercised before it is abused, and that abuse presupposes exercise" (Ricoeur 57).',
          expect=[("ricoeur", "memory is exercised before it is abused", "57")]),
    QCase("curly_quotes",
          'Booth reminds us that “the author’s judgment is always present, always evident” (Booth 20).',
          expect=[("booth", "judgment is always present", "20")]),
    QCase("title_hint_disambiguates",
          'Stevens asks "what is the point of worrying oneself too much about what one could or could not have done" (Ishiguro, Remains 244).',
          expect=[("remains", "worrying oneself too much", "244")]),
    QCase("ambiguous_bare_surname_skipped",
          'Kathy recalls that "we took away your art because we thought it would reveal your souls" (Ishiguro 255).',
          must_skip=["we took away your art"]),
    QCase("two_author_citation",
          'One critic argues the novel "stages the very failure of self-knowledge it describes" (Phelan and Martin 91).',
          expect=[("phelan", "stages the very failure", "91")]),
    QCase("two_quotes_one_paragraph",
          'Ricoeur writes that "forgetting is the emblem of the vulnerability of the historical condition" and later that "the duty of memory is the duty to do justice" (Ricoeur 284).',
          expect=[("ricoeur", "forgetting is the emblem", "284"),
                  ("ricoeur", "the duty of memory", "284")]),
    QCase("mid_length_quote",
          'Nunning calls this "a projection by the reader" (Nunning 87).',
          expect=[("nunning", "a projection by the reader", "87")]),
    QCase("fragment_scare_quote_skipped",
          'The so-called "unreliable" narrator remains contested (Booth 158).',
          must_skip=["unreliable"]),
    QCase("no_citation_skipped",
          'Someone once said "quotations without citations are just decoration for the desperate reader."',
          must_skip=["quotations without citations"]),
    QCase("pages_range",
          'The essay insists that "narrative judgments unfold in time and revise themselves" (Phelan and Martin 92-93).',
          expect=[("phelan", "narrative judgments unfold", "92-93")]),
    QCase("qtd_in",
          'As Woolf observed, "books continue each other" (qtd. in Booth 41).',
          expect=[("booth", "books continue each other", "41")]),
    QCase("citation_before_second_sentence",
          'The claim appears early (Ricoeur 12). He states that "testimony constitutes the fundamental transition between memory and history" there.',
          expect=[("ricoeur", "testimony constitutes the fundamental transition", "12")]),
    QCase("no_pages_still_links",
          'She notes that "the ethics of reading begins with attention to what the text withholds" (Nunning).',
          expect=[("nunning", "ethics of reading begins", "")]),
    QCase("ambiguous_two_quotes_all_skipped",
          '"In bantering lies the key to human warmth" is answered by "poor creatures, what can you do?" (Ishiguro 258).',
          must_skip=["bantering lies the key", "poor creatures"]),
]


def run_corpus():
    from uuid import UUID
    from app.canonical.model import ParagraphBlock, Run, ThesisDocument
    from app.ingest.citations import resolve_citation, scan_document
    from app.verification.inline_quotes import extract_inline_quotes

    class _Src:
        def __init__(self, fields):
            self.fields = fields

    source_ids = {key: uuid4() for key in SOURCES}
    source_map = {source_ids[k]: _Src(v) for k, v in SOURCES.items()}
    id_to_key = {str(v): k for k, v in source_ids.items()}

    doc = ThesisDocument.model_validate({
        "meta": {"title": "Quote Corpus"}, "front_matter": [], "works_cited": [],
        "chapters": [{"number": 1, "title": "C", "blocks": []}],
    })
    block_for_case: dict[str, str] = {}
    for case in CASES:
        block = ParagraphBlock(runs=[Run(text=case.paragraph)])
        doc.chapters[0].blocks.append(block)
        block_for_case[case.id] = str(block.id)

    citation_by_block: dict[str, dict] = {}
    for citation in scan_document(doc):
        resolved, _cands, reason = resolve_citation(citation, source_map)
        citation_by_block[citation.block_id] = {
            "resolved_source_id": str(resolved) if resolved else None,
            "pages": citation.pages, "raw": citation.raw, "reason": reason,
        }
    quotes = extract_inline_quotes(doc, citation_by_block)
    by_block: dict[str, list] = {}
    for q in quotes:
        by_block.setdefault(q.block_id, []).append(q)
    return block_for_case, by_block, id_to_key


def score():
    block_for_case, by_block, id_to_key = run_corpus()
    expected = captured = 0
    fabrications: list[str] = []
    rows = []
    for case in CASES:
        got = by_block.get(block_for_case[case.id], [])
        detail = {"id": case.id, "misses": [], "fabs": []}
        for src_key, substring, pages in case.expect:
            expected += 1
            hit = next((q for q in got if substring in q.text), None)
            if hit is None:
                detail["misses"].append(f"missing quote ~ {substring!r}")
            elif id_to_key.get(hit.source_id) != src_key:
                detail["fabs"].append(f"{substring!r} linked to WRONG source {id_to_key.get(hit.source_id)}")
                fabrications.append(f"{case.id}:{substring[:24]}")
            elif pages and hit.pages != pages:
                detail["fabs"].append(f"{substring!r} wrong pages {hit.pages!r} != {pages!r}")
                fabrications.append(f"{case.id}:pages")
            else:
                captured += 1
        for substring in case.must_skip:
            if any(substring in q.text for q in got):
                detail["fabs"].append(f"MUST-SKIP captured: {substring!r}")
                fabrications.append(f"{case.id}:must_skip")
        rows.append(detail)
    return {
        "recall": round(captured / expected, 3) if expected else 0.0,
        "captured": captured, "expected": expected,
        "fabrications": fabrications,
    }, rows


if __name__ == "__main__":
    metrics, rows = score()
    print(f"quote recall : {metrics['captured']}/{metrics['expected']} = {metrics['recall']:.1%}")
    print(f"fabrications : {len(metrics['fabrications'])} {metrics['fabrications'][:6]}")
    for row in rows:
        if row["misses"] or row["fabs"]:
            print(f"  {row['id']}: misses={row['misses']} fabs={row['fabs']}")
