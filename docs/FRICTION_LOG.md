# FRICTION_LOG — Priya's first-run gauntlet

**Method.** A fresh browser, a new user ("Priya Ramesh", MA English, MCC, three
weeks from deadline), and one goal: turn a real messy 40-page DOCX (4 chapters
with deliberately inconsistent headings, 5 inline quotations, 25 Works-Cited
entries including several malformed) into a submission-ready output — using only
what the UI shows, no docs, no API, no developer knowledge. Every confusion >10s
is logged; ranked by *"would Priya quit here?"*. Screenshots in `/tmp/priya/`.

The engine underneath is genuinely strong — 25 sources parsed, a 68% Submission
Readiness dial with honest per-dimension bars, integrity findings with evidence.
**None of that matters if Priya quits in the first five minutes, and right now
she would.** These are the reasons, worst first.

---

## P0 — Total blockers (Priya cannot proceed at all)

### F1 · Signup's first click returns "Request failed (500)" — FIXED
The very first action — "Email code" — 500'd. Two independent causes:
- **Rate-limiter header bug (production-critical, self-inflicted).** The limiter
  ran with `headers_enabled=True`, which makes slowapi require every decorated
  endpoint to expose a Starlette `Response`. Our endpoints return Pydantic
  models, so **every rate-limited route 500s the moment `RATE_LIMIT_ENABLED` is
  true — the production default.** The 507-test suite never caught it because
  conftest disables rate limiting globally. In production, signup and ~a dozen
  endpoints would be dead on arrival. *Fixed this session* (`headers_enabled=
  False`; enforcement still works, only the informational headers are dropped).
  Needs a regression test that runs *with* limiting on.
- **First-run bootstrap.** `request-otp` 500s ("default institution missing")
  when no institution matches `DEFAULT_INSTITUTION_SHORT_NAME`. A freshly
  deployed instance therefore rejects its very first user. *Worked around* by
  seeding the MCC institution; needs a real idempotent bootstrap (see Fix #1).

*Quit risk before fix: 100%. She never gets in.* Screenshot: `02_after_email.png`.

---

## P1 — She gets in, then thinks the product ate her thesis

### F2 · After upload, her chapters are invisible ("Structure 0%")
Priya uploads 40 pages and the Structure sidebar shows only "Works Cited · 0" —
**no chapters** — and the editor says "Select a chapter…" when there are none to
select. The Integrity dial confirms **Structure 0%**. Root cause (verified
against the model): the deterministic parser extracted only **2 of her 4
chapters, and the wrong two** — it *missed* "INTRODUCTION" (a real Heading 1)
and "Chapter Two" (manual bold), and *falsely* promoted a plain lowercase
paragraph to a chapter. It logs `coverage=1.0` — confidently wrong. Real
students format headings chaotically; the parser assumes they don't.
*This is the single most damaging moment: "where is my thesis?"*
Screenshots: `07_after_upload.png`, `10_review.png`.

### F3 · The "parsing queued" banner never resolves
Every tab still shows the green "Original preserved. Preflight and deterministic
parsing are queued." banner — even after parsing finished. There is no success
state, no "✓ 25 sources and 2 chapters imported" summary, no spinner→done. Priya
can't tell whether the system is working, done, or stuck. Async work needs a
visible lifecycle. Screenshot: `08_structure_after_import.png`.

---

## P2 — She's oriented but stuck on next steps

### F4 · Two different "titles", and the one that matters is empty
The project shows her title in the header, yet Integrity blocks with "Required
metadata is missing: title." There are *two* title concepts — the project title
and the submission-metadata title (Front matter) — and nothing tells her the
second exists or that it's what gates readiness. She'll stare at a title on
screen being told her title is missing. Screenshot: `10_review.png`.

### F5 · 87 open issues, no "start here"
The Integrity badge climbs from 16 → 87 as validation completes. 87 findings
with a Severity/Category/Status filter is a triage tool for an expert, not a
next-step for a panicking student. There's no "Fix these 3 blockers first" lane.

### F6 · Her 5 inline quotations weren't captured
"Quotation registry: No quotation records yet." Priya's thesis *contains* 5
quotations with page numbers; the product's flagship feature is quote
verification — but nothing offered to extract them. She'd have to hand-link each,
and nothing tells her to. The gap between "I have quotes" and "the system knows
my quotes" is unbridged at exactly the feature that sells. Screenshot:
`09_registry.png`.

### F7 · Everything says "[VERIFY]" — reads as "everything is broken"
All 25 imported sources are tagged `[VERIFY]`. This is *correct* (nothing is
auto-trusted — the integrity discipline), but with zero framing it reads to a
first-timer as "25 errors." One line — "Imported. Confirm each source when
ready." — turns alarm into a to-do.

---

## Would-Priya-finish verdict

Before F1's fix: **no** — she never signs in. After it, with today's UI: **still
no** — F2/F3 make her believe the upload failed. Fix F1–F4 and she reaches the
readiness dial understanding what to do next, which is the whole game.

---

## The 5 smallest changes that get Priya to the outcome

Ordered by (quit-risk removed ÷ effort). Proposals only — no features touched.

1. **First-run bootstrap + graceful auth failure** *(~1–2h)*. On startup,
   idempotently ensure an institution matching `DEFAULT_INSTITUTION_SHORT_NAME`
   exists; and make `request-otp` return a friendly 200 message instead of 500
   when institution resolution fails. Kills F1's second cause for every future
   deploy. *(F1's rate-limit half is already fixed; add the regression test.)*

2. **Post-import success summary + resolve the banner** *(~2–3h)*. When
   ingestion finishes, replace the "queued" banner with "✓ Imported N sources,
   M chapters — X need attention," and refresh the Structure sidebar. Directly
   fixes F3 and softens F2/F7; pure front-end + one status read.

3. **Parser heading-recovery pass** *(~4–6h)*. Add a fallback that recognizes
   common student heading patterns (ALL-CAPS lines, "Chapter N", roman numerals,
   bold single-line paragraphs) when Word Heading styles are absent, and stop
   promoting plain paragraphs. Lift Structure off 0% on real documents. Biggest
   effort, biggest payoff for F2 — but scope it tight to detection only.

4. **Reconcile the two titles** *(~1h)*. Default the submission-metadata title
   from the project title on creation, and label the Front-matter field
   "Submission title (appears on the cover page)". Removes the F4 contradiction.

5. **Blocker-first triage lane** *(~2h)*. Above the 87-issue list, a "3 things
   blocking submission" card that shows only `block`-severity findings with a
   jump link. Turns F5's wall into a path; reuses existing findings data.

**Recommended pick:** #1 + #2 first (half a day, removes both P0/P1 quit-cliffs),
then #4, then #3 when there's a real block of time. #3 is where the product
becomes trustworthy on real files — but it's the one to do carefully, not fast.
