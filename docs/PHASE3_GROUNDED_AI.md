# Phase 3 — Grounded AI Thesis Partner

Phase 3 adds project-scoped academic assistance without giving an AI agent direct authorship authority over the canonical thesis.

The canonical `Project` remains the source of truth. AI output is stored as conversation, analysis, memory, research queries, viva questions, or an inert structured proposal. A proposal changes the document only after a human explicitly selects operations and the existing Phase 2 command engine accepts them.

## Non-negotiable authority boundary

Robofox Scholar may:

- inspect a permitted project/chapter/block/review/source/quotation scope;
- explain, diagnose, challenge and plan;
- generate search strategies without claiming to browse;
- refresh project/chapter memory and argument maps;
- generate viva-preparation questions;
- create a structured proposal containing narrowly permitted operations.

It may not:

- write directly to canonical project JSON;
- verify a source or quotation;
- approve a chapter or thesis;
- dismiss an integrity violation;
- trigger final export or submission;
- change an institutional format profile;
- invent bibliographic data or direct quotations;
- claim it browsed, opened a URL, or confirmed an external source;
- grade the thesis or help evade AI-detection systems.

The only mutation path is:

```text
AI output
→ strict JSON schema
→ semantic proposal validator
→ stored inert proposal
→ human reviews each operation
→ human accepts selected operations
→ Phase 2 command engine
→ optimistic version check
→ undoable command and snapshot history
→ deterministic verifier and review inbox
```

## Canonical project and legacy continuity

Legacy `ThesisSession` rows can be linked to a v2/v3 Project. Their coaching messages and fields are preserved as historical, private context. They never override:

- canonical chapters and front matter;
- the current thesis statement/project metadata;
- registered sources and quotations;
- supervisor constraints in project AI policy;
- current document version or review state.

Every Phase 3 thread belongs to one Project and one user.

## Scoped context compiler

Each run compiles only what its task needs:

1. task policy and project AI policy;
2. safe project metadata;
3. selected canonical blocks or chapter map;
4. active-revision sources and quotations;
5. relevant open review findings;
6. current hierarchical memory;
7. a bounded number of recent messages from the selected private thread;
8. the current user request.

Candidate registration numbers and unrelated private data are not included merely because they exist in project metadata.

Every document/source/quote/message section is XML-escaped and wrapped as `<untrusted_content>`. Manuscript text cannot promote itself into system instructions.

The stored context manifest records:

- document and schema versions;
- active manuscript revision;
- exact scope;
- chapter/block IDs and hashes;
- source and quotation IDs;
- which records were human-verified;
- review-item and memory IDs;
- prompt-injection findings;
- omitted or truncated sections;
- explicit `external_research_available: false`;
- a SHA-256 context hash.

## Task modes and server-side routing

The server—not user wording—selects risk, output type, model tier and allowed operations.

| Mode | Purpose | Output | Mutation authority |
|---|---|---|---|
| `understand` | explain/summarise selected content | conversation | none |
| `diagnose` | claim/evidence/analysis/transition review | analysis | none |
| `plan` | reviewable revision sequence | proposal | markers, paragraph insertion, bounded moves |
| `transform` | bounded prose revision | proposal | selected block edits, paragraph/marker/verified-quote insertion |
| `challenge` | sceptical examiner/counterargument | conversation | none |
| `research` | search strategies and candidate metadata | research queries | none |
| `coherence` | whole-thesis contradiction/drift scan | analysis | none |
| `viva` | defence-readiness questions | conversation | none |
| `memory_refresh` | project/chapter summaries, argument map, literature matrix | memory | none |

Strong whole-project tasks are quota-limited separately from utility tasks.

## Proposal operation contract

The AI output schema allows only:

- `replace_runs`
- `insert_paragraph`
- `insert_marker`
- `move_block`
- `add_verified_quote`

Semantic validation additionally enforces:

- targets must exist inside the compiled scope;
- text replacement is limited to paragraph and heading blocks;
- quotation blocks cannot be rewritten by the AI;
- long quotation-like text cannot be smuggled through prose operations;
- marker kinds are allowlisted;
- cross-chapter movement is high risk;
- cited evidence IDs must have been present in compiled context;
- `add_verified_quote` requires an active human-verified quotation and human-verified source;
- the backend inserts the exact registry text—the AI never supplies quotation text;
- missing evidence becomes an unresolved requirement or visible marker.

## Human decision and stale proposals

A proposal is bound to the document version and stable hashes of the content examined.

- Block/selection proposals survive unrelated edits elsewhere.
- They become stale when an examined block changes.
- Chapter/project proposals become stale when the scoped chapter structure/content changes.
- Stale proposals cannot be applied and must be regenerated.

The user may:

- accept selected operations;
- accept all operations;
- edit an operation before acceptance;
- reject with a structured reason;
- supersede/regenerate a stale proposal.

Human-edited operation payloads are preserved separately from the original AI proposal. High-risk structural operations require a written decision note.

Accepted operations become one Phase 2 command/batch so they are undoable. The proposal stores verifier reports before and after application.

## Direct quotations and evidence types

Proposal evidence distinguishes:

- direct quotation;
- paraphrase;
- summary;
- primary-text observation;
- critical interpretation;
- contextual factual claim.

A direct quotation can enter the thesis only through a `quote_id` from the human-verified registry. If none exists, Robofox must state what evidence is missing or propose a `QUOTE_NEEDED`/`EVIDENCE_NEEDED` marker.

## Hierarchical memory and argument map

AI memory records are navigation aids, never source-of-truth document content.

Supported memory kinds include:

- project and chapter summaries;
- thesis argument map;
- voice profile based on approved writing;
- literature-review matrix.

Each record is tied to a document version, prompt version and model. Canonical edits mark older derived memories stale. `memory_refresh` regenerates them without changing thesis text.

## Controlled research pipeline

Phase 3 does not enable unrestricted browsing. Robofox may formulate search queries and purposes. Candidate records move through an explicit lifecycle:

```text
candidate
→ metadata_confirmed
→ accessed
→ added_registry
```

A candidate cannot be added to the source registry until the user records that the source was accessed. Even then it enters as:

- `verified = false`;
- `parse_status = structured_with_review`;
- human verification required.

A search snippet never becomes evidence or a quotation.

## Prompt-injection defence

The compiler scans untrusted content for instruction-like patterns such as:

- “ignore previous instructions”;
- fake system/developer messages;
- commands to mark records verified/approved;
- secret/prompt extraction attempts;
- embedded tool/shell/browser instructions.

Findings are included in provenance but do not grant authority. The provider runtime continues to use:

- no tools;
- strict empty MCP configuration;
- no session persistence;
- one structured JSON response.

## Capacity, cancellation and degraded mode

Configurable Phase 3 controls:

- global kill switch;
- per-project kill switch and allowed task modes;
- one or more supervisor constraints in project policy;
- per-user concurrent-run limit;
- per-project queue limit;
- daily run limit;
- stronger-model daily limit;
- context character budget;
- proposal operation limit.

AI work uses the durable PostgreSQL queue. Queued runs can be cancelled immediately. A running provider call may finish, but a cancellation flag causes its result to be discarded.

When AI is disabled, unavailable, rate-limited or degraded:

- editing remains available;
- review and verification remain available;
- sources/quotes remain available;
- preview and export remain available;
- existing proposals/history remain readable.

AI provider health is deliberately not a hard `/readyz` dependency.

## Provenance and export disclosure

Each completed run records:

- model;
- prompt name/version;
- context hash and manifest;
- selected scope;
- token/cost usage where available;
- proposal ID;
- injection findings.

Each accepted proposal records:

- original operations;
- selected indexes;
- human-edited payloads;
- decision note and rejection reason where applicable;
- resulting command ID;
- verifier reports before and after.

Export manifests receive a privacy-preserving AI disclosure summary containing task modes, model/prompt versions, accepted proposal/operation counts and human-edited operation counts. Raw private conversations are not included.

## Thesis-specific evaluation benchmark

Run:

```bash
python scripts/run_phase3_evals.py
```

The deterministic corpus covers:

- output schema violations;
- fabricated/unregistered quotations;
- quotation-text smuggling;
- false browsing claims;
- verification/approval overreach;
- AI-detection evasion;
- prompt injection treated as data;
- safe evidence markers;
- safe viva questions.

Release CI requires:

- expectation match rate: `1.0`;
- unsafe acceptance rate: `0.0`;
- migration `head → 0009 → head`;
- Phase 3 safety and API suites;
- the complete inherited repository suite.

## Phase 3 acceptance flow

1. Open a canonical project and select a stable block/chapter scope.
2. Choose a task mode.
3. Review the UI’s exact scope statement.
4. Queue a grounded run.
5. Read the explanation, analysis, evidence, assumptions and missing requirements.
6. Review each proposed operation independently.
7. Optionally edit operation JSON.
8. Accept selected operations with a decision note where required.
9. Phase 2 applies one undoable command and increments document version.
10. Review/verifier state updates and output preview becomes stale.
11. Generate viva questions or refresh argument-map memory.
12. Export disclosure reports accepted AI involvement without revealing private chat.

## Deliberate Phase 3 exclusions

- autonomous full-thesis generation;
- direct AI database/document writes;
- unrestricted web/MCP/browser access;
- AI source or quotation verification;
- AI approval, grading, submission or export authority;
- AI-detection evasion;
- real-time multi-agent swarms;
- supervisor collaboration permissions and institutional billing.

## Deployment status

Phase 3 is developed on a stacked branch after Phase 2. It must not be merged or deployed until Phase 1, Phase 2 and Phase 3 PRs are deliberately reviewed and merged in order, all migrations/tests pass, and the existing Oracle readiness procedure succeeds.
