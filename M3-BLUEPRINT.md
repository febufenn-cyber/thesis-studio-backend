# M3 Blueprint — Mode B wiring (for the implementing session)

The hard engine is DONE and tested (`app/ingest/`, commit 7b053a9, 88 tests).
This document specifies the remaining mechanical work. Follow repo CLAUDE.md
conventions (async SQLAlchemy, isolation 404s, no new deps, type hints).

## 0. Engine contract (import, don't reimplement)

```python
from app.ingest.docx_extract import extract_paragraphs   # (path) -> list[ExtractedPara]
from app.ingest.structure import parse_manuscript        # (paras) -> ParseResult
#   ParseResult: .document (ThesisDocument, works_cited EMPTY)
#                .wc_raw_entries (list[list[Run]])
#                .ambiguous (list[Ambiguity{chapter, block_index, reason, text_preview}])
#                .parse_notes (list[str])
from app.ingest.citations import parse_wc_entries, scan_document, VERIFY
#   parse_wc_entries(wc_raw_entries) -> list[SourceCandidate{kind, fields, verify_note, raw_entry}]
from app.ingest.verifier import verify                   # (doc, sources_by_id, quotes_by_id) -> VerifierReport
#   report.as_dict() == {"pass", "violations":[{rule,location,found,expected,severity}], "counts"}
```

## 1. No migration needed

- Manuscript bytes → storage service key `manuscripts/{user_id}/{project_id}/{uuid}.docx`.
- Parse artifacts (notes, ambiguities, source count) → `events` row,
  `kind="manuscript_ingested"`, `data={...}` (cap ambiguous list at 100).
- Verifier runs → `events` row `kind="verify_run"`, `data=report.as_dict()`.

## 2. Routes (add to app/api/projects.py)

### POST /projects/{id}/manuscript  → 200 IngestReport
Body (JSON — deliberately NOT multipart, avoids the python-multipart dep):
`{filename: str, content_base64: str}`. Reject >15MB decoded, non-.docx.
Steps (all inside one handler, engine does the work):
1. `fetch_owned_project`; 409 if `project.chapters` already non-empty
   (re-ingest = archive + new project; keeps history simple).
2. Decode to a `tempfile`, upload original via storage service (audit copy).
3. `paras = extract_paragraphs(tmp)`; `result = parse_manuscript(paras)`.
4. `candidates = parse_wc_entries(result.wc_raw_entries)`; for each: insert
   `Source(project_id, user_id, kind, fields, verified=False,
   verify_note=cand.verify_note or None)`. Keep insertion order.
5. `project.works_cited = [{"source_id": str(s.id)} for s in created_sources]`
   (order matches candidates — that invariant comes from step 4).
6. Quote registration: walk `result.document.chapters[*].blocks`; for each
   block_quote/verse_quote with a `citation`, match surname (first word of
   citation) against created sources' author surnames; on match create
   `Quote(source_id, project_id, user_id, page_or_loc=<digits in citation>,
   text=<block text / joined lines>, verified=False, method="extracted")`
   and set the block's `quote_id = str(quote.id)` in the JSON. No match →
   leave `quote_id` null (verifier will flag it; operator resolves).
7. Persist: `project.front_matter/chapters` from
   `result.document.model_dump(mode="json")`; `project.status="formatting"`.
8. Event row; return `{chapters: n, front_matter: [...kinds], sources: n,
   quotes_linked: n, verify_fields: <count of sources with [VERIFY]>,
   ambiguous: [...], parse_notes: [...]}`.

### PATCH /projects/{id}/sources/{source_id} → SourceResponse
Body `{fields?: dict, verified?: bool, consulted_flag?: bool}` — the operator
resolves `[VERIFY]` values and attests sources. Ownership: project AND
source.user_id checks (404).

### POST /projects/{id}/verify → 200 VerifierReport
Build inputs: `doc = build_thesis_document(project)` (export_service),
`sources = {s.id: s}`, `quotes = {q.id: q}` for the project. Return
`verify(...).as_dict()`, store Event.

### Export gating (edit trigger_exports in projects.py)
Before creating Export rows: run the verifier; if `counts["block"] > 0`,
409 with `{detail: "Verifier blocks export", report: ...}`. Keep G4
acknowledge check as-is (Mode B: that checkbox IS the operator attestation).

## 3. Operator UI (app/static/index.html — extend existing vanilla patterns)

New top-level view `projectsView` reachable from the sessions screen header
("Formatting studio" button):
- Project list (GET /projects) + create form (title, format_profile select).
- Project detail: upload card (file input → FileReader → base64 → POST
  manuscript), then three panels fed by the ingest report + GET endpoints:
  1. **Structure** — chapters/front-matter summary + ambiguity list
     (chapter/block + reason) for manual review.
  2. **Registry** — sources table; `[VERIFY]` fields rendered as inputs;
     save → PATCH source; verified toggle.
  3. **Verify & Export** — "Run verifier" button → violations table
     (severity-colored); export buttons (docx/pdf/md/txt + acknowledge
     checkbox) → poll GET exports (reuse the compile-poll pattern) →
     download links.
Keep everything cookie-authed `fetch`, `createElement` only (no innerHTML
with user data), stop pollers on view switch.

## 4. Tests (tests/test_ingest_api.py)

Reuse `_build_manuscript` from tests/test_ingest.py (import it). Cases:
upload unauthenticated 401 / cross-user 404 / happy path (assert sources
created in WC order, works_cited linked, quotes matched to Achebe, status
formatting, event row) / re-upload 409 / PATCH source resolves [VERIFY] /
verify endpoint returns block for the unmatched-quote case then passes after
operator fixes / export blocked by verifier 409 then allowed. Whole suite
must stay green (88 existing).

## 5. Deploy

git pull on VM + `pm2 restart thesis-api` (no migration). LibreOffice still
absent → pdf exports fail with the clean message; install
`libreoffice-core-nogui` + `ttf-mscorefonts-installer` when PDF is wanted
(956MB RAM — watch swap during conversions).

## 6. Explicitly out of scope (later milestones)

LLM assist for ambiguous blocks (MANUSCRIPT_PARSER prompt exists in
files/PROMPTS.md — wire through ClaudeService only when deterministic
parsing proves insufficient on real manuscripts), .md/.txt ingestion,
exemplar StyleProfiles (M4), Mode A gates (M5–M6).
