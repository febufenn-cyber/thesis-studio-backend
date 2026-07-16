"""Frozen works-cited extraction corpus + scorer (eval-first, FRICTION F7-root).

APPEND-ONLY after freeze: never delete or soften a case to make the number go
up. If a case is genuinely ambiguous, the correct output is a [VERIFY] flag —
argue in a comment, don't game it.

Ground truth policy (never-guess): `expect` fields must be extracted verbatim
(trailing period/whitespace normalised). `absent` fields MUST come back as
[VERIFY]/empty — any concrete value there is a FABRICATION and counts 10x
worse than a miss. Entries marked broken=True must be flagged
(parse_status == "structured_with_review").

Most cases are PLAIN TEXT (no italic runs) — the discovered real-world
condition: students paste works cited without formatting, so italic-only
title detection collapses. A few italic cases keep the styled path honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Case:
    id: str
    text: str
    kind: str
    expect: dict = field(default_factory=dict)
    absent: tuple = ()
    broken: bool = False
    italics: tuple = ()  # substrings that are italic runs (styled cases)


CASES: list[Case] = [
    # ---- books, plain text (the collapse condition) ----
    Case("book_plain_1", "Ishiguro, Kazuo. The Remains of the Day. Faber and Faber, 1989.",
         "book", {"author": "Ishiguro, Kazuo", "title": "The Remains of the Day",
                  "publisher": "Faber and Faber", "year": "1989"}),
    # same-author dash: must inherit Ishiguro from the previous entry
    Case("book_dash_inherit", "---. Never Let Me Go. Faber and Faber, 2005.",
         "book", {"author": "Ishiguro, Kazuo", "title": "Never Let Me Go",
                  "publisher": "Faber and Faber", "year": "2005"}),
    Case("book_edition", "Booth, Wayne C. The Rhetoric of Fiction. 2nd ed., U of Chicago P, 1983.",
         "book", {"author": "Booth, Wayne C.", "title": "The Rhetoric of Fiction",
                  "publisher": "U of Chicago P", "year": "1983"}),
    Case("book_translated",
         "Ricoeur, Paul. Memory, History, Forgetting. Translated by Kathleen Blamey and David Pellauer, U of Chicago P, 2004.",
         "translated_book",
         {"author": "Ricoeur, Paul", "title": "Memory, History, Forgetting",
          "translator": "Kathleen Blamey and David Pellauer",
          "publisher": "U of Chicago P", "year": "2004"}),
    Case("book_colon_commas",
         "Currie, Mark. About Time: Narrative, Fiction and the Philosophy of Time. Edinburgh UP, 2007.",
         "book", {"author": "Currie, Mark", "title": "About Time: Narrative, Fiction and the Philosophy of Time",
                  "publisher": "Edinburgh UP", "year": "2007"}),
    Case("book_plain_2", "Wong, Cynthia F. Kazuo Ishiguro. Northcote House, 2000.",
         "book", {"author": "Wong, Cynthia F.", "title": "Kazuo Ishiguro",
                  "publisher": "Northcote House", "year": "2000"}),
    Case("book_plain_3", "Shaffer, Brian W. Understanding Kazuo Ishiguro. U of South Carolina P, 1998.",
         "book", {"author": "Shaffer, Brian W.", "title": "Understanding Kazuo Ishiguro",
                  "publisher": "U of South Carolina P", "year": "1998"}),
    Case("book_plain_4", "Lodge, David. The Art of Fiction. Penguin, 1992.",
         "book", {"author": "Lodge, David", "title": "The Art of Fiction",
                  "publisher": "Penguin", "year": "1992"}),
    Case("book_plain_5", "Genette, Gerard. Narrative Discourse. Cornell UP, 1980.",
         "book", {"author": "Genette, Gerard", "title": "Narrative Discourse",
                  "publisher": "Cornell UP", "year": "1980"}),
    Case("book_plain_6", "Fludernik, Monika. An Introduction to Narratology. Routledge, 2009.",
         "book", {"author": "Fludernik, Monika", "title": "An Introduction to Narratology",
                  "publisher": "Routledge", "year": "2009"}),
    Case("book_old", "James, Henry. The Art of the Novel. Scribner, 1934.",
         "book", {"author": "James, Henry", "title": "The Art of the Novel",
                  "publisher": "Scribner", "year": "1934"}),
    Case("book_plain_7", "Chatman, Seymour. Story and Discourse. Cornell UP, 1978.",
         "book", {"author": "Chatman, Seymour", "title": "Story and Discourse",
                  "publisher": "Cornell UP", "year": "1978"}),
    Case("book_plain_8", "Cohn, Dorrit. Transparent Minds. Princeton UP, 1978.",
         "book", {"author": "Cohn, Dorrit", "title": "Transparent Minds",
                  "publisher": "Princeton UP", "year": "1978"}),
    Case("book_edition_2",
         "Abbott, H. Porter. The Cambridge Introduction to Narrative. 2nd ed., Cambridge UP, 2008.",
         "book", {"author": "Abbott, H. Porter", "title": "The Cambridge Introduction to Narrative",
                  "publisher": "Cambridge UP", "year": "2008"}),
    Case("book_edition_3", "Bal, Mieke. Narratology: Introduction to the Theory of Narrative. 3rd ed., U of Toronto P, 2009.",
         "book", {"author": "Bal, Mieke", "title": "Narratology: Introduction to the Theory of Narrative",
                  "publisher": "U of Toronto P", "year": "2009"}),
    Case("book_plain_9", "Whitehead, Anne. Trauma Fiction. Edinburgh UP, 2004.",
         "book", {"author": "Whitehead, Anne", "title": "Trauma Fiction",
                  "publisher": "Edinburgh UP", "year": "2004"}),
    Case("book_publisher_two_words", "Teo, Yugin. Kazuo Ishiguro and Memory. Palgrave Macmillan, 2014.",
         "book", {"author": "Teo, Yugin", "title": "Kazuo Ishiguro and Memory",
                  "publisher": "Palgrave Macmillan", "year": "2014"}),
    Case("book_two_authors",
         "Herman, David, and Becky McHale. Teaching Narrative Theory. MLA, 2010.",
         "book", {"author": "Herman, David, and Becky McHale", "title": "Teaching Narrative Theory",
                  "publisher": "MLA", "year": "2010"}),
    Case("book_et_al",
         "Smith, John, et al. Narrative Across Media. U of Nebraska P, 2019.",
         "book", {"author": "Smith, John, et al", "title": "Narrative Across Media",
                  "publisher": "U of Nebraska P", "year": "2019"}),
    Case("book_editors_as_authors",
         "Groes, Sebastian, and Barry Lewis, editors. Kazuo Ishiguro: New Critical Visions. Palgrave, 2011.",
         "book", {"author": "Groes, Sebastian, and Barry Lewis, editors",
                  "title": "Kazuo Ishiguro: New Critical Visions",
                  "publisher": "Palgrave", "year": "2011"}),
    Case("book_edition_rev",
         "Rimmon-Kenan, Shlomith. Narrative Fiction: Contemporary Poetics. 2nd ed., Routledge, 2002.",
         "book", {"author": "Rimmon-Kenan, Shlomith", "title": "Narrative Fiction: Contemporary Poetics",
                  "publisher": "Routledge", "year": "2002"}),
    # ---- books, italic-styled (the styled path must keep winning) ----
    Case("book_italic",
         "Austen, Jane. Emma. John Murray, 1815.",
         "book", {"author": "Austen, Jane", "title": "Emma",
                  "publisher": "John Murray", "year": "1815"},
         italics=("Emma",)),
    Case("book_italic_translated",
         "Eco, Umberto. The Name of the Rose. Translated by William Weaver, Harcourt, 1983.",
         "translated_book",
         {"author": "Eco, Umberto", "title": "The Name of the Rose",
          "translator": "William Weaver", "publisher": "Harcourt", "year": "1983"},
         italics=("The Name of the Rose",)),
    # ---- journal articles ----
    Case("journal_plain",
         'Nunning, Ansgar. "Unreliable Narration Reconsidered." Style, vol. 35, no. 1, 2001, pp. 151-78.',
         "journal", {"author": "Nunning, Ansgar", "title": "Unreliable Narration Reconsidered",
                     "container": "Style", "volume": "35", "number": "1",
                     "year": "2001", "pages": "151-78"}),
    Case("journal_italic",
         'Phelan, James. "Estranging Unreliability." Narrative, vol. 15, no. 2, 2007, pp. 222-38.',
         "journal", {"author": "Phelan, James", "title": "Estranging Unreliability",
                     "container": "Narrative", "volume": "15", "number": "2",
                     "year": "2007", "pages": "222-38"},
         italics=("Narrative",)),
    Case("journal_db_plain",
         'Zerweck, Bruno. "Historicizing Unreliable Narration." Style, vol. 35, no. 1, 2001, pp. 151-78. JSTOR, www.jstor.org/stable/10.5325/style.35.1.151.',
         "journal_db", {"author": "Zerweck, Bruno", "title": "Historicizing Unreliable Narration",
                        "container": "Style", "volume": "35", "number": "1",
                        "year": "2001", "pages": "151-78", "database": "JSTOR"}),
    Case("journal_two_authors",
         'Lanser, Susan S., and Robyn Warhol. "Gender and Narrative." Poetics Today, vol. 39, no. 1, 2018, pp. 1-16.',
         "journal", {"author": "Lanser, Susan S., and Robyn Warhol", "title": "Gender and Narrative",
                     "container": "Poetics Today", "volume": "39", "number": "1",
                     "year": "2018", "pages": "1-16"}),
    # ---- chapters in collections ----
    Case("chapter_plain",
         'Phelan, James, and Mary Patricia Martin. "The Lessons of Weymouth." Narratologies, edited by David Herman, Ohio State UP, 1999, pp. 88-109.',
         "chapter_in_collection",
         {"author": "Phelan, James, and Mary Patricia Martin", "title": "The Lessons of Weymouth",
          "container": "Narratologies", "editor": "David Herman",
          "publisher": "Ohio State UP", "year": "1999", "pages": "88-109"}),
    Case("chapter_italic",
         'Cohn, Dorrit. "Discordant Narration." A Companion to Narrative Theory, edited by James Phelan, Blackwell, 2005, pp. 494-508.',
         "chapter_in_collection",
         {"author": "Cohn, Dorrit", "title": "Discordant Narration",
          "container": "A Companion to Narrative Theory", "editor": "James Phelan",
          "publisher": "Blackwell", "year": "2005", "pages": "494-508"},
         italics=("A Companion to Narrative Theory",)),
    # ---- web sources ----
    Case("web_plain",
         'Flood, Alison. "Kazuo Ishiguro Wins the Nobel Prize." The Guardian, 5 Oct. 2017, www.theguardian.com/books/2017/oct/05/kazuo-ishiguro-wins-nobel.',
         "web", {"author": "Flood, Alison", "title": "Kazuo Ishiguro Wins the Nobel Prize",
                 "site": "The Guardian", "url": "www.theguardian.com/books/2017/oct/05/kazuo-ishiguro-wins-nobel"}),
    Case("web_no_author",
         '"The Nobel Prize in Literature 2017." NobelPrize.org, www.nobelprize.org/prizes/literature/2017/summary.',
         "web", {"title": "The Nobel Prize in Literature 2017",
                 "site": "NobelPrize.org", "url": "www.nobelprize.org/prizes/literature/2017/summary"}),
    # ---- film ----
    Case("film_plain",
         "The Remains of the Day. Directed by James Ivory, Merchant Ivory Productions, 1993.",
         "film", {"title": "The Remains of the Day", "director": "James Ivory",
                  "studio": "Merchant Ivory Productions", "year": "1993"},
         italics=("The Remains of the Day",)),
    # ---- genuinely broken: correct output IS the flag ----
    Case("broken_no_container_year",
         'Nunning, Ansgar. "Unreliable Narration Reconsidered."',
         "web", {"title": "Unreliable Narration Reconsidered"},
         absent=("site", "url"), broken=True),
    Case("broken_fragment_no_publisher",
         "Zerweck, Bruno. Historicizing Unreliable Narration",
         "book", {"author": "Zerweck, Bruno"},
         absent=("publisher", "year"), broken=True),
    Case("broken_interview_fragment",
         "Ishiguro interview, The Paris Review, 2008.",
         "book", {},
         absent=("author", "title", "publisher"), broken=True),
    Case("broken_bare_url",
         "www.ishigurosociety.org/essays/voice",
         "book", {},
         absent=("author", "title", "publisher", "year"), broken=True),
    Case("broken_no_title",
         "Anonymous. Unknown Press, 2020.",
         "book", {},
         absent=("title",), broken=True),
    Case("broken_missing_punct",
         "Rimmon-Kenan, Shlomith. Narrative Fiction. Routledge 2002",
         "book", {"author": "Rimmon-Kenan, Shlomith", "title": "Narrative Fiction"},
         absent=("publisher",), broken=True),
]

VERIFY = "[VERIFY]"


def _norm(value: str) -> str:
    return str(value or "").strip().rstrip(".").strip()


def run_corpus():
    """Parse the whole corpus IN ORDER (dash inheritance is order-dependent)."""
    from app.canonical.model import Run
    from app.ingest.citations import parse_wc_entries

    raw = []
    for case in CASES:
        if case.italics:
            runs, rest = [], case.text
            for marker in case.italics:
                before, _, after = rest.partition(marker)
                if before:
                    runs.append(Run(text=before))
                runs.append(Run(text=marker, italic=True))
                rest = after
            if rest:
                runs.append(Run(text=rest))
        else:
            runs = [Run(text=case.text)]
        raw.append((0, runs))
    return parse_wc_entries(raw)


def score():
    """Returns metrics dict + per-case detail rows."""
    results = run_corpus()
    labeled = correct = 0
    fabrications: list[str] = []
    broken_total = broken_flagged = 0
    rows = []
    for case, cand in zip(CASES, results):
        detail = {"id": case.id, "kind_ok": cand.kind == case.kind, "misses": [], "fabs": []}
        for fname, want in case.expect.items():
            labeled += 1
            got = _norm(cand.fields.get(fname, ""))
            if got == _norm(want):
                correct += 1
            elif got and VERIFY not in got:
                detail["fabs"].append(f"{fname}: wanted {want!r} got {got!r}")
                fabrications.append(f"{case.id}.{fname}")
            else:
                detail["misses"].append(f"{fname}: wanted {want!r} got VERIFY")
        for fname in case.absent:
            got = _norm(cand.fields.get(fname, ""))
            if got and VERIFY not in got:
                detail["fabs"].append(f"{fname}: must be VERIFY, got {got!r}")
                fabrications.append(f"{case.id}.{fname}!absent")
        if case.broken:
            broken_total += 1
            if cand.parse_status == "structured_with_review":
                broken_flagged += 1
            else:
                detail["misses"].append("NOT FLAGGED though broken")
        rows.append(detail)
    return {
        "field_recall": round(correct / labeled, 3) if labeled else 0.0,
        "labeled": labeled,
        "correct": correct,
        "fabrications": fabrications,
        "broken_flagged": f"{broken_flagged}/{broken_total}",
        "broken_ok": broken_flagged == broken_total,
    }, rows


if __name__ == "__main__":
    metrics, rows = score()
    print(f"field recall : {metrics['correct']}/{metrics['labeled']} = {metrics['field_recall']:.1%}")
    print(f"fabrications : {len(metrics['fabrications'])} {metrics['fabrications'][:8]}")
    print(f"broken flagged: {metrics['broken_flagged']}")
    for row in rows:
        if row["misses"] or row["fabs"] or not row["kind_ok"]:
            print(f"  {row['id']}: kind_ok={row['kind_ok']} misses={row['misses']} fabs={row['fabs']}")
