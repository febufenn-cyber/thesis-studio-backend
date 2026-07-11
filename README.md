# Robofox Thesis Studio — Backend

FastAPI backend for Robofox Thesis Studio. The application preserves the legacy AI-guided workflow, provides Phase 1 trusted manuscript conversion, and adds the Phase 2 human review and structured editing workspace.

## Quick start

```bash
# 1. Clone and enter the repo
git clone <this-repo> thesis-studio-backend
cd thesis-studio-backend

# 2. Python environment
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configuration
cp .env.example .env
# At minimum configure:
#   JWT_SECRET (run `openssl rand -hex 32`)
#   ANTHROPIC_API_KEY or the configured Claude CLI path

# 4. Database
docker-compose up -d postgres
alembic upgrade head

# 5. Create an institution so users can sign up
python scripts/create_institution.py \
    --name "Madras Christian College (Autonomous)" \
    --short-name "MCC" \
    --domains "mcc.edu.in,students.mcc.edu.in" \
    --address "Tambaram, Chennai – 600 059." \
    --short-address "Tambaram, Chennai – 59" \
    --university "University of Madras" \
    --department "PG & Research Department of English" \
    --aided

# 6. Run the API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 7. In a second terminal, run the durable worker
source venv/bin/activate
python -m app.services.job_queue
```

Open `http://localhost:8000/` for the Phase 2 human review cockpit. The preserved legacy coach remains at `http://localhost:8000/legacy`.

Open `http://localhost:8000/docs` for the interactive API documentation when `DEBUG=true`.

## Phase 1 — Trusted manuscript conversion

Phase 1 accepts a `.docx` manuscript, preserves the exact original and checksum, parses it into a provenance-rich canonical document, exposes unsupported and ambiguous content for human review, verifies citations/sources/quotations, and produces version-bound review or final exports.

Core guarantees:

- immutable manuscript revisions and restore;
- stable UUID locations and original paragraph provenance;
- DOCX ZIP/preflight validation with no silent content loss;
- exact human citation-resolution records;
- active-revision-isolated source and quotation verification;
- optimistic concurrency and stale-export protection;
- durable PostgreSQL jobs with retries and worker heartbeats;
- verifier-gated final exports and clearly labelled review exports;
- post-render DOCX/PDF QA and chain-of-custody manifests.

See [`docs/PHASE1_TRUSTED_CONVERSION.md`](docs/PHASE1_TRUSTED_CONVERSION.md).

## Phase 2 — Human review and editing workspace

Phase 2 converts the canonical thesis into a safe human correction workflow. It is deliberately a structured thesis editor rather than a browser clone of Microsoft Word.

### Review cockpit

The root application provides:

- a document structure tree with chapter, heading and front-matter states;
- chapter-level lazy loading for large manuscripts;
- block-level paragraph, heading, quotation, verse and marker editing;
- original-import versus current-text comparison;
- persistent review inbox with stable issue identities;
- deterministic readiness scores with transparent component counts;
- guided metadata/front-matter forms;
- renderer-backed source forms and exact citation-resolution actions;
- quotation-registry comparison and verification;
- structural preview plus authoritative PDF preview;
- append-only history, checkpoints, comparison, restore, undo and redo;
- explicit stale-export warnings;
- offline browser-draft preservation and conflict messaging;
- keyboard navigation, reduced-motion support and mobile review mode.

### Structured editing guarantees

- Normal editing uses fine-grained commands rather than replacing whole JSONB chapter collections.
- Every command includes the expected document version.
- Browser autosave retries are idempotent through a client request ID.
- The server generates the inverse command from the actual previous state.
- Cross-chapter moves and command batches use an exact whole-document inverse.
- Undo and redo append new commands rather than rewriting history.
- Older history is restored through immutable snapshots.
- Editing reviewed or approved content returns it to `needs_review`.
- Editing cited prose removes stale exact-citation decisions.
- Editing a linked quotation invalidates its verification.
- Locked chapters reject content mutations.
- Institution-controlled title/certificate/declaration presentation remains profile-driven.

### Review and preview guarantees

- Blocking integrity findings cannot be dismissed manually.
- Eligible warnings and human import judgments may be acknowledged with a recorded note.
- Review findings reopen automatically when the underlying problem recurs.
- The fast structural preview is explicitly approximate.
- Authoritative previews run through the real DOCX → LibreOffice PDF pipeline.
- Preview cache identity is project + document version + profile version.
- Ready exports retain the exact document version and are labelled stale after later edits.

See [`docs/PHASE2_HUMAN_REVIEW.md`](docs/PHASE2_HUMAN_REVIEW.md).

## Project structure

```text
app/
├── api/             # Auth, legacy, manuscripts, editor, review and preview APIs
├── canonical/       # Canonical thesis model and JSON-data migrations
├── core/            # Settings, JWT and security helpers
├── db/              # SQLAlchemy engine, sessions and dependencies
├── editor/          # Pure structured command engine and safe inverse wrapper
├── ingest/          # DOCX preflight, extraction, parsing and citation verification
├── models/          # ORM models, including commands/snapshots/review/previews
├── renderers/       # Governed profiles and DOCX/PDF/Markdown/Text renderers
├── schemas/         # Pydantic API contracts
├── services/        # Jobs, ingestion, editing, review, preview, export and storage
├── static/          # Phase 2 cockpit and preserved legacy frontend
└── main.py          # FastAPI application entry point

migrations/          # Alembic relational migrations
scripts/             # Deployment and operational scripts
tests/               # Isolation, regression, Phase 1 and Phase 2 tests
```

## Important Phase 2 API groups

### Editor

- `GET /projects/{id}/editor/structure`
- `GET /projects/{id}/editor/chapters/{chapter_id}`
- `GET /projects/{id}/editor/blocks/{block_id}/context`
- `POST /projects/{id}/editor/commands`
- `POST /projects/{id}/editor/commands/{command_id}/undo`
- `POST /projects/{id}/editor/commands/{command_id}/redo`
- `GET /projects/{id}/editor/search`

### Snapshots and comparison

- `POST /projects/{id}/editor/snapshots`
- `GET /projects/{id}/editor/snapshots`
- `GET /projects/{id}/editor/snapshots/{snapshot_id}/compare`
- `POST /projects/{id}/editor/snapshots/{snapshot_id}/restore`

### Review

- `GET /projects/{id}/review-items`
- `PATCH /projects/{id}/review-items/{review_item_id}`
- `GET /projects/{id}/readiness`
- `GET /citation-source-kinds`
- `POST /projects/{id}/citation-resolutions`

### Preview

- `POST /projects/{id}/previews`
- `GET /projects/{id}/previews`
- `GET /previews/{preview_id}`
- `GET /previews/{preview_id}/file`

## Legacy workflow

`POST /sessions/{id}/compile` returns 202 and starts the preserved legacy compile workflow. Poll `GET /sessions/{id}/files` until a file with `status="ready"` appears, then use `GET /files/{id}/download`.

Phase 1/2 project exports use `POST /projects/{id}/exports` and the durable PostgreSQL worker. Poll `GET /projects/{id}/exports` and `GET /projects/{id}/jobs`.

## Health and readiness

- `GET /healthz` — API liveness only.
- `GET /readyz` — database, Alembic head, worker heartbeat, stuck jobs, storage/disk, LibreOffice/font stack and production email readiness.

Production deployment must require `/readyz`, not only `/healthz`.

## Testing

Tests use a separate PostgreSQL database, configured in `docker-compose.yml`.

```bash
docker-compose up -d postgres-test
pytest -v

# Phase 1 contracts
pytest tests/test_phase1_unit.py -v

# Phase 2 pure command invariants
pytest tests/test_phase2_unit.py -v

# Phase 2 database/API workflow and citation resolution
pytest tests/test_phase2_api.py tests/test_phase2_citation_api.py -v

# Critical tenant isolation
pytest tests/test_isolation.py -v
```

The dedicated Phase 2 GitHub Actions workflow validates:

- Python compilation;
- all four Phase 2 JavaScript modules;
- Alembic `head → 0008 → head` migration round trip;
- canonical JSON v2 → v3 behavior;
- structured editor invariants;
- editor/review/preview/citation API workflows;
- the full repository regression suite.

Validated Phase 2 completion results:

- **9 Phase 2 command/review invariants passed**;
- **7 Phase 2 API and citation-resolution tests passed**;
- **114 tests passed overall**.

## Deployment

Production deploys to the Oracle Cloud VM hosting `robofox.online`:

```bash
scripts/deploy_to_oracle.sh
```

The deployment script installs missing runtime packages, creates swap when needed, upgrades the schema, starts or reloads `thesis-api` and `thesis-worker`, and fails unless `/readyz` passes.

Manual equivalent on the VM:

```bash
cd /opt/thesis-studio-backend
git fetch origin
git reset --hard origin/main
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
pm2 startOrReload ecosystem.config.js --update-env
pm2 save
curl -fsS http://127.0.0.1:8000/readyz
```

The Nginx configuration proxies the public Thesis Studio domain to `127.0.0.1:8000`.

## Phase isolation

Each implementation phase is developed on its own branch and pull request. Do not mix later-phase AI or collaboration changes into the Phase 2 branch, and do not merge or deploy a phase until its dedicated and inherited CI workflows pass.

## Documentation

- [`docs/PHASE1_TRUSTED_CONVERSION.md`](docs/PHASE1_TRUSTED_CONVERSION.md) — manuscript conversion, provenance, verification, deployment and rollback.
- [`docs/PHASE2_HUMAN_REVIEW.md`](docs/PHASE2_HUMAN_REVIEW.md) — editor commands, review inbox, snapshots, preview, accessibility and acceptance flow.
- `CLAUDE.md` — standing coding-agent instructions.
- `app/formatter/SKILL.md` when present — legacy format specification.
- `/docs` with `DEBUG=true` — OpenAPI documentation.

## Stack

- Python 3.11, FastAPI and SQLAlchemy 2.0 async
- PostgreSQL 14+ and Alembic
- PostgreSQL-backed durable job queue
- Canonical Pydantic thesis model with independent JSON-data migrations
- Anthropic/Claude legacy coaching and compile integration
- Cloudflare R2 or local storage
- Resend transactional email
- python-docx and LibreOffice for governed Word/PDF rendering
