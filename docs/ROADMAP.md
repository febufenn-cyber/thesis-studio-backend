# Acadensia Roadmap — Research-Grade, Domain-Agnostic, Integrity-First

Status: brainstorm / living document. Scope: what comes after the domain-expansion
release (v0.7.0, schema 0021). This is a menu and a sequence, not a commitment.

---

## 1. Positioning

Acadensia is a governed, canonical-model thesis platform. The bet is that the
document is not a blob of text but a structured, provenance-bearing artifact:
every block has identity and origin, every citation resolves through a
never-guess discipline, and every phase is gated. That structure is the moat.
Most writing tools treat the manuscript as prose with formatting on top;
Acadensia treats it as data with a rendering on top. Everything below leans into
that difference rather than competing on editor polish.

Three audiences, one platform:

- **Degree candidates** (MA, PhD, engineering, STEM, arts, design, law) who need
  correct citations, submission-readiness, and defensible authorship.
- **Researchers** submitting to venues (NeurIPS, ACL, CVPR, IMRaD journals) who
  need compliance, reproducibility artifacts, and LaTeX-native workflows.
- **Institutions and supervisors** who need governance, integrity assurance, and
  auditable provenance without policing their own students.

## 2. Design principles carried forward

New work should respect the invariants that made the core trustworthy:

- **Never guess.** A field is resolved, cited, or absent — never fabricated. New
  data sources must fail closed the way `_require` does today.
- **Canonical first.** Features attach to block identity and origin, not to
  rendered text or line numbers, so they survive re-rendering and re-styling.
- **Three seams.** Expansion continues to land in the established seams
  (citation styles, domain profiles, reference interchange) rather than
  threading new concerns through the integrity core.
- **Governed phases.** Anything that changes the manuscript's meaning is a
  phase-gated, attributable action, not a silent mutation.

---

## 3. Directions

### 3.1 AI provenance and authorship integrity

**What.** Turn `BlockOrigin` into a first-class provenance ledger: per block (and
ideally per run) record whether text was human-authored, AI-suggested and
accepted, AI-generated then human-edited, or imported. Roll this up into an
auto-generated **AI Use Statement** that maps to institutional and journal
disclosure policies, and expose a **provenance timeline** for a manuscript.

**Why.** This is the most defensible direction in the current climate, and the
branch that shipped the expansion was already named for it. Positioned as
*transparency the author owns and can present*, it earns trust from integrity
offices and researchers simultaneously — the opposite of a detector arms race.

**Sub-features.**

- Provenance capture at edit time (author action → origin tag), with an
  immutable append-only event log keyed to block identity.
- Disclosure templates per domain profile (a NeurIPS statement differs from a
  university's DPDP-aligned declaration).
- A signed provenance attestation (extends the existing attestation/submission
  path) so a supervisor can verify the statement wasn't edited after the fact.
- Optional redaction: the author chooses granularity (document-level summary vs
  section-level vs block-level) before export.

**Seams / architecture.** Builds on `canonical/model.py` (`BlockOrigin`,
`MarkerKind`), the attestation/submission FK chain, and the export renderers (a
new "AI Use" section generator). Mostly an aggregation service plus a new
export section; the model groundwork exists.

**Effort / risk.** Medium. Low technical risk, high policy sensitivity — the
templates must be accurate to real institutional/venue policies, so this is a
research-the-policies-first task, not a guess-the-format one.

### 3.2 Reference enrichment and reconciliation

**What.** Resolve the `[VERIFY]` placeholders automatically. Paste a DOI, arXiv
id, ISBN, or a messy free-text citation and get back clean, verified metadata,
de-duplicated and retraction-checked.

**Why.** You already have 14 styles and BibTeX/RIS import; the missing half is
trustworthy *input*. This converts the never-guess discipline from a constraint
("we won't fill this") into a capability ("we resolved this from an authority").

**Sub-features.**

- Resolver chain: Crossref (DOI, journal metadata), OpenAlex (broad coverage,
  open), Semantic Scholar (CS/AI depth), arXiv (preprints), Unpaywall (OA
  links), ISBN services (books). Fail closed: unresolved stays `[VERIFY]`.
- Retraction and correction flags via Crossref/Retraction Watch, surfaced in
  readiness so a thesis never unknowingly cites a retracted work.
- Duplicate/variant reconciliation: the same work cited three ways collapses to
  one canonical source with alternate keys preserved.
- Confidence and provenance on each resolved field (which authority, when),
  because a resolved field is still a claim about the world.

**Seams / architecture.** New `app/references/resolvers/` behind an interface
mirroring the citation-style registry; feeds the existing source model and
`field_schema.missing_required`. Import endpoints already exist to hang this off.

**Effort / risk.** Medium. Main risks are rate limits and metadata quality —
mitigated by caching resolutions and always showing the source authority so a
human can override.

### 3.3 Quotation and claim verification

**What.** Given a source document (PDF/EPUB/HTML), confirm that a quoted passage
actually appears in it, verbatim, at the cited location — and flag paraphrases
that drift. Longer horizon: **claim–citation alignment**, i.e. does the cited
source actually support the sentence it is attached to.

**Why.** This is the thesis-specific extension of the anti-hallucination core.
Verbatim/page verification is tractable and immediately valuable. Alignment is a
genuine research problem, which is exactly why it makes the platform interesting
to build research *on*.

**Sub-features.**

- Quote verification: fuzzy-locate the quotation in the source, confirm exact
  wording, verify the page/locator, and flag near-misses (transcription drift).
- Page-number and locator sanity for author-page and notes styles.
- Paraphrase attribution: detect an unquoted claim that closely tracks a source
  and prompt for a citation.
- (Research) claim–support scoring: an NLI-style check that the cited span
  entails the manuscript sentence, surfaced as advisory, never as a hard gate.

**Seams / architecture.** A verification service consuming source artifacts +
canonical runs; hooks into the existing verification/readiness services. The
alignment layer is where an AI-researcher plugin surface would live.

**Effort / risk.** Verbatim verification: medium, low risk. Alignment: high,
research-grade — ship it as opt-in and clearly probabilistic.

### 3.4 Venue and submission compliance

**What.** Make the venue domain profiles *enforce*, not just template. Page
limits, anonymization for double-blind, reproducibility checklists, and
one-click camera-ready formatting.

**Why.** This is where "AI researchers should love it" becomes concrete: it
removes the error-prone last mile before a deadline. Profiles already exist for
NeurIPS/ACL/CVPR; enforcement is the payoff.

**Sub-features.**

- Page/length budget checking against the compiled artifact, per venue.
- Double-blind anonymization lint: self-citations that leak identity,
  acknowledgements, funding lines, non-anonymized links/repos.
- Reproducibility checklist (e.g. NeurIPS-style) as a gated readiness step tied
  to the submission checklist already in `DomainProfile`.
- Camera-ready formatter: apply the venue's template deterministically from the
  canonical model.

**Seams / architecture.** Extends `domains/profiles.py` (add validators to a
profile), the readiness/`domain-readiness` endpoint, and the compile path.

**Effort / risk.** Medium, incremental — each validator is independently
shippable and testable.

### 3.5 Interoperability and deposit

**What.** Close the loop from writing to a citable, published artifact. Two
formats unlock most of it: **JATS XML** (journal submission standard) and
**LaTeX import** to complement the existing export.

**Sub-features.**

- JATS XML export so a finished manuscript can enter a publisher's system.
- LaTeX import (arXiv/Overleaf round-trip) so LaTeX-native researchers aren't
  forced out of their workflow; pairs with existing `to_latex`.
- ORCID for author identity; institutional-repository deposit (DSpace/Zenodo)
  with a minted DOI.
- DOCX with tracked changes and CSL-JSON round-trip (export exists; add import).

**Seams / architecture.** New renderers/importers alongside `bibtex`, `ris`,
`csl`, `latex`; deposit is an outbound integration behind a small adapter.

**Effort / risk.** JATS/LaTeX-import: medium. Deposit integrations: medium and
partner-dependent (credentials, sandbox testing).

### 3.6 Supervision and committee workflow

**What.** The institution-driving layer on top of the existing project-scoped
approval and collaboration primitives.

**Sub-features.**

- Advisor/committee roles with scoped permissions (ties into the deferred
  institution-scoped lifecycle authz item).
- Feedback anchored to canonical block identity, so comments survive
  re-rendering and re-styling instead of drifting with line numbers.
- Semantic version diffing between drafts (what *changed in meaning*, not just
  text), leveraging the canonical model.
- Defense/viva prep view: assemble figures, claims, and their verified sources.

**Seams / architecture.** Extends `collaboration/workflow.py` and the presence
migration; the block-anchored comments reuse block identity directly.

**Effort / risk.** Medium-high; the authz model is the sensitive part (self vs
advisor vs admin; privacy regime) — the one flagged as deferred for good reason.

### 3.7 Multilingual and non-English scholarship

**What.** First-class support for theses not written in English: language-aware
citation norms, transliteration, RTL rendering, and locale-correct typography.

**Why.** A large share of the world's graduate writing is non-English, and most
tools treat it as an afterthought. This widens the addressable base and is a
credible differentiator.

**Sub-features.** Locale-specific citation ordering and punctuation;
transliteration handling in author names; RTL and CJK rendering; per-language
submission templates.

**Seams / architecture.** Citation-style registry gains locale variants; the
renderer families already separate mechanism from text, which helps.

**Effort / risk.** Medium-high; typography and RTL are detail-heavy. Sequence
after the resolver work, which supplies clean multilingual metadata.

### 3.8 The platform as a research instrument

**What.** With opt-in consent and rigorous anonymization, Acadensia sits on a
structured corpus of *how academic writing is actually made* — revision
histories, citation patterns, AI-assistance provenance. Exposed carefully, that
becomes a dataset almost no one has, and a reason researchers study *with*
Acadensia rather than merely using it.

**Guardrails.** Opt-in only, aggregate/differential-privacy by default, ethics
review, and clear data-governance boundaries. This is a trust feature or a
liability depending entirely on how it's built — so it's a "later," gated behind
the provenance and governance work.

**Effort / risk.** High, and as much policy/ethics as engineering. Highest
ceiling of anything on this list, and the truest expression of the original bar
("an AI researcher should love to do their research and publish with it").

---

## 4. Phased sequence

**Now (highest leverage, lowest new risk).**

1. Reference enrichment and reconciliation (3.2) — retires the `[VERIFY]` debt,
   immediately visible, and everything downstream benefits from clean metadata.
2. AI provenance rollup and AI Use Statement (3.1) — timely, defensible, model
   groundwork already exists.
3. Quotation verification, verbatim + locator (3.3, first half) — extends the
   integrity core with a tractable, testable feature.

**Next.**

4. Venue compliance enforcement (3.4) — turns existing profiles into the thing
   deadline-driven researchers evangelize.
5. Interop: JATS export + LaTeX import (3.5) — meets researchers in their
   existing toolchains.
6. Supervision workflow, block-anchored feedback + roles (3.6) — the
   institutional wedge; do the authz carefully.

**Later.**

7. Claim–citation alignment (3.3, research half).
8. Multilingual scholarship (3.7).
9. Research-instrument corpus (3.8), gated behind provenance + governance.

Rationale: each "Now" item pays off on its own, de-risks the next, and none
requires reopening the integrity core. Clean metadata (3.2) precedes multilingual
(3.7) and alignment (3.3b); provenance (3.1) precedes the corpus (3.8).

## 5. Open research questions (the build-on-it surface)

These are deliberately unsolved, and are where an AI-researcher plugin/extension
surface would live:

- Can claim–citation *support* be scored reliably enough to be advisory without
  being misleading? What's the right calibration and UI for probabilistic flags?
- What is the minimal, verifiable provenance record that satisfies both journal
  disclosure and student privacy — and can it be made cryptographically sound
  without being burdensome?
- Can reference reconciliation reach a precision where auto-resolved metadata is
  trusted by default, and how is disagreement between authorities adjudicated?
- What does semantic (meaning-level) diffing of scholarly drafts look like, and
  is it useful to supervisors in practice?

## 6. Non-goals (for now)

- Becoming a general-purpose word processor or beating editors on WYSIWYG polish.
- Detector-style "AI or not" policing — provenance is author-declared and
  attested, not inferred and accused.
- Silent auto-fixing of citations or claims — everything stays never-guess and
  attributable.

---

*Sequencing and scope are provisional. Each direction is designed to land in an
existing seam and to preserve the never-guess, canonical-first, governed-phase
invariants that make the core trustworthy.*
