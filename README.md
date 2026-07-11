# Robofox Thesis Studio — Backend

FastAPI backend for Robofox Thesis Studio. The application preserves the legacy AI-guided thesis workflow and adds three governed product layers:

1. **Trusted manuscript conversion** — preserve, parse, verify and export an uploaded thesis.
2. **Human review workspace** — safely correct the canonical thesis through structured, reversible commands.
3. **Grounded AI thesis partner** — inspect, challenge and propose without silently becoming the author.

## Quick start

```bash
# Clone and enter the repository
git clone <this-repo> thesis-studio-backend
cd thesis-studio-backend

# Python environment
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configuration
cp .env.example .env
# Set a secure JWT secret and the existing Claude/provider configuration.

# Database
docker-compose up -d postgres
alembic upgrade head

# Create an institution if the database is empty
python scripts/create_institution.py \
    --name "Madras Christian College (Autonomous)" \
    --short-name "MCC" \
    --domains "mcc.edu.in,students.mcc.edu.in" \
    --address "Tambaram, Chennai – 600 059." \
    --short-address "Tambaram, Chennai – 59" \
    --university "University of Madras" \
    --department "PG & Research Department of English" \
    --aided

# API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Durable worker in a second terminal
source venv/bin/activate
python -m app.services.job_queue
```

Open `http://localhost:8000/` for the structured thesis workspace. The preserved legacy coaching interface remains at `http://localhost:8000/legacy`.

## Phase 1 — Trusted manuscript conversion

Phase 1 accepts a `.docx`, preserves the original and SHA-256 checksum, detects unsupported content, parses a provenance-rich canonical document, exposes ambiguity for review, verifies citations/sources/quotations, and produces version-bound review or final exports.

Core guarantees:

- immutable manuscript revisions and restoration;
- stable chapter/front-matter/block UUIDs;
- source paragraph and revision provenance;
- DOCX ZIP/preflight validation;
- unsupported objects reported rather than silently discarded;
- conservative citation resolution;
- active-revision-isolated source and quotation registries;
- durable PostgreSQL ingestion/export jobs;
- verifier-gated final exports;
- clearly labelled review exports;
- post-render QA and chain-of-custody manifests.

See [`docs/PHASE1_TRUSTED_CONVERSION.md`](docs/PHASE1_TRUSTED_CONVERSION.md).

## Phase 2 — Human review and editing workspace

Phase 2 replaces raw JSON as the normal editing path with a structured review cockpit.

It provides:

- chapter-level lazy loading and stable deep links;
- paragraph, heading, quotation, verse and marker editing;
- block insert/delete/duplicate/move/split/merge/type conversion;
- run-preserving paragraph changes so italics survive;
- optimistic concurrency and idempotent autosave;
- append-only commands with exact inverse operations;
- undo/redo, checkpoints, snapshot comparison and restore;
- persistent review items with deterministic re-opening;
- dependency-aware invalidation of review/citation/quote trust;
- original-versus-current comparison;
- template-driven source and metadata forms;
- exact citation-occurrence resolution;
- cached authoritative PDF preview;
- stale export visibility;
- browser draft recovery, accessibility and mobile review mode.

See [`docs/PHASE2_HUMAN_REVIEW.md`](docs/PHASE2_HUMAN_REVIEW.md).

## Phase 3 — Grounded AI thesis partner

Phase 3 introduces AI into the governed canonical workspace without giving it direct mutation, verification, approval, export or submission authority.

### Authority boundary

The canonical Project is the sole source of truth. Robofox Scholar may inspect and propose, but every document operation must follow:

```text
AI response
→ strict output schema
→ semantic safety validation
→ inert proposal
→ human selects/edits operations
→ Phase 2 command engine
→ version check + undo history
→ deterministic verification
```

AI cannot:

- directly edit project JSON;
- verify sources or quotations;
- approve chapters;
- resolve blocking integrity findings;
- trigger export/submission;
- change institutional format profiles;
- claim external browsing;
- invent or reproduce direct quotations outside the verified quote registry;
- grade the thesis or assist AI-detection evasion.

### Grounded task modes

- `understand` — explain or summarise selected content;
- `diagnose` — identify claim/evidence/analysis/transition weaknesses;
- `plan` — propose a reviewable revision sequence;
- `transform` — propose bounded prose operations;
- `challenge` — act as a sceptical examiner;
- `research` — generate search strategies without browsing claims;
- `coherence` — detect whole-thesis contradiction and drift;
- `viva` — generate defence-readiness questions without grading;
- `memory_refresh` — refresh summaries, argument map and literature matrix.

The server selects risk, output type, model tier and allowed operations. User wording cannot escalate permissions or force a stronger model.

### Bounded context and prompt-injection defence

For each run, the server compiles only the selected canonical scope, relevant active-revision sources/quotations, related review issues, current project memory and a bounded recent thread window.

All manuscript/source/quotation/message text is XML-escaped and wrapped as untrusted data. The context manifest records exact IDs, hashes, versions, verified evidence IDs, truncation, injection findings and a SHA-256 context hash.

The provider process remains tool-disabled, MCP-isolated and sessionless.

### Human-controlled proposals

Permitted proposal operations are restricted to:

- `replace_runs`
- `insert_paragraph`
- `insert_marker`
- `move_block`
- `add_verified_quote`

Direct quotations can be inserted only by `quote_id` from a currently human-verified quotation whose source is also human-verified. The backend—not the model—copies the exact registered text.

Users may accept selected operations, accept all, edit an operation before acceptance, reject with a structured reason, or regenerate stale proposals. High-risk structural changes require a decision note. Accepted operations become one undoable Phase 2 command/batch.

### Memory, research and viva preparation

Phase 3 adds:

- project/chapter summaries;
- thesis argument maps;
- voice-profile and literature-matrix memory records;
- version-aware memory invalidation;
- controlled research candidates;
- explicit candidate lifecycle before registry import;
- mandatory human verification after candidate import;
- evidence-grounded viva questions and challenge mode;
- preserved legacy coaching history linked to canonical projects.

A search snippet never becomes evidence, and an imported research candidate is always unverified.

### Capacity and degraded mode

AI runs use the durable PostgreSQL worker and support idempotency, progress, cancellation, retry and stale-result suppression.

Environment-configurable controls include:

```text
AI_GLOBAL_ENABLED
AI_MAX_CONTEXT_CHARS
AI_RECENT_THREAD_MESSAGES
AI_USER_CONCURRENT_LIMIT
AI_PROJECT_QUEUE_LIMIT
AI_DAILY_RUN_LIMIT
AI_DAILY_STRONG_RUN_LIMIT
AI_MAX_PROPOSAL_OPERATIONS
```

Project policy also controls AI enablement, allowed modes, private threads, supervisor constraints and disclosure requirements.

When the AI provider is unavailable or disabled, editing, verification, sources, previews and exports continue to work.

### AI provenance and disclosure

Every run/proposal records:

- model;
- prompt name/version;
- document version and selected scope;
- context manifest/hash;
- evidence IDs and assumptions;
- original operations;
- selected and human-edited operations;
- decision/rejection information;
- resulting command;
- verifier reports before and after.

Final export manifests contain a privacy-preserving AI disclosure summary. Raw private conversations are not included.

See [`docs/PHASE3_GROUNDED_AI.md`](docs/PHASE3_GROUNDED_AI.md).

## Phase 3 evaluation benchmark

Run:

```bash
python scripts/run_phase3_evals.py
```

The current release gate covers ten safe/adversarial cases including:

- invalid output authority fields;
- fabricated quotation insertion;
- quotation text smuggling;
- false browsing claims;
- verification/approval overreach;
- AI-detection evasion;
- prompt injection treated as document data;
- safe evidence markers;
- safe viva questions.

The required release thresholds are:

```text
expectation_match_rate = 1.0
unsafe_acceptance_rate = 0.0
```

## Project structure

```text
app/
├── ai/              # scoped context, safety, provider, proposals, memory and evals
├── api/             # auth, projects, manuscripts, editor, review and AI routes
├── canonical/       # stable canonical thesis model and JSON migrations
├── core/            # application settings and security helpers
├── db/              # async SQLAlchemy engine/session/dependencies
├── editor/          # deterministic Phase 2 command engine
├── ingest/          # DOCX inspection, parsing and verification
├── models/          # ORM models
├── renderers/       # governed DOCX/PDF/Markdown/Text renderers
├── services/        # jobs, export, preview, storage, readiness and legacy AI
├── static/          # review cockpit and grounded AI workspace
└── main.py

migrations/          # relational migrations through Phase 3
scripts/             # deployment and evaluation commands
tests/               # inherited, phase-specific and adversarial suites
```

## Health and readiness

- `GET /healthz` — API liveness.
- `GET /readyz` — database, migration head, worker heartbeat, stuck jobs, storage/disk, LibreOffice/font and production-email readiness.
- `GET /projects/{id}/ai/health` — AI availability, capacity and degraded-mode state.

AI provider availability is intentionally not a hard `/readyz` dependency.

## Tests

```bash
docker-compose up -d postgres-test
pytest -v
pytest tests/test_phase1_unit.py -v
pytest tests/test_phase2_unit.py tests/test_phase2_api.py -v
pytest tests/test_phase3_unit.py tests/test_phase3_evals.py tests/test_phase3_api.py -v
python scripts/run_phase3_evals.py
```

Phase 3 completion validation on its functional head:

- Python compilation: passed;
- all five workspace JavaScript modules: passed;
- Alembic `head → 0009 → head`: passed;
- Phase 3 safety invariants: **9 passed**;
- grounded AI benchmark: **10/10 expected outcomes**, **0% unsafe acceptance**;
- Phase 3 API/proposal/research workflows: **6 passed**;
- complete repository suite: **131 passed**;
- inherited Phase 1 and Phase 2 workflows: passed.

## Deployment

```bash
scripts/deploy_to_oracle.sh
```

Deployment upgrades the database, starts/reloads both API and durable worker processes, and requires `/readyz` success.

The phase branches are stacked and must be reviewed and merged in order:

```text
Phase 1 → Phase 2 → Phase 3 → main → production deployment
```

No phase branch should be merged or deployed automatically.

## Documentation

- [`docs/PHASE1_TRUSTED_CONVERSION.md`](docs/PHASE1_TRUSTED_CONVERSION.md)
- [`docs/PHASE2_HUMAN_REVIEW.md`](docs/PHASE2_HUMAN_REVIEW.md)
- [`docs/PHASE3_GROUNDED_AI.md`](docs/PHASE3_GROUNDED_AI.md)
- `CLAUDE.md` — standing coding-agent and safety instructions
- `/docs` with `DEBUG=true` — OpenAPI documentation

## Stack

- Python 3.11, FastAPI, SQLAlchemy 2 async, PostgreSQL 14+
- Alembic and PostgreSQL-backed durable jobs
- tool-disabled structured Claude CLI adapter plus preserved legacy coaching
- Cloudflare R2 or local storage
- Resend transactional email
- python-docx and LibreOffice for governed output
