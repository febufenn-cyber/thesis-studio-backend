# Robofox Thesis Studio — Backend

FastAPI backend for Robofox Thesis Studio. The application preserves the legacy AI-guided thesis workflow and adds a Phase 1 integrity-first manuscript conversion workspace.

## Quick start (local development)

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
# Edit .env — at minimum set:
#   JWT_SECRET (run `openssl rand -hex 32`)
#   ANTHROPIC_API_KEY (or the configured Claude CLI path)

# 4. Database
docker-compose up -d postgres
alembic upgrade head

# 5. Create an institution (so users can sign up)
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

# 7. In a second terminal, run the durable Phase 1 worker
source venv/bin/activate
python -m app.services.job_queue
```

Open `http://localhost:8000/` for the Phase 1 operator workspace. The legacy app remains at `http://localhost:8000/legacy`.

Visit `http://localhost:8000/docs` for the interactive API docs when `DEBUG=true`.

## Phase 1 trusted conversion

Phase 1 accepts a `.docx` manuscript, preserves the exact original and checksum, parses it into a provenance-rich canonical document, queues ambiguous/unsupported content for human review, verifies citations/sources/quotations, and produces version-bound review or final exports.

Core guarantees:

- immutable manuscript revisions and restore;
- stable UUID locations and source paragraph provenance;
- DOCX ZIP/preflight validation with no silent loss;
- exact human citation-resolution records;
- active-revision-isolated source and quotation verification;
- optimistic concurrency and stale-export protection;
- durable PostgreSQL jobs with retries and worker heartbeats;
- verifier-gated final exports and clearly labelled review exports;
- post-render DOCX/PDF QA and chain-of-custody manifests.

See [`docs/PHASE1_TRUSTED_CONVERSION.md`](docs/PHASE1_TRUSTED_CONVERSION.md) for the complete operator and deployment runbook.

## Project structure

```text
app/
├── api/             # Auth, legacy workflow, projects, manuscripts, review APIs
├── canonical/       # Stable canonical thesis model
├── core/            # Settings, JWT, security helpers
├── db/              # SQLAlchemy engine, session factory, dependencies
├── ingest/          # DOCX preflight, extraction, parsing, citation verification
├── models/          # ORM models
├── renderers/       # Governed profiles and DOCX/PDF/Markdown/Text renderers
├── schemas/         # Pydantic request/response shapes
├── services/        # Jobs, ingestion, verification, export, email, storage
├── static/          # Phase 1 workspace and legacy frontend
└── main.py          # FastAPI app entry point

migrations/          # Alembic migrations
scripts/             # Deployment and operational scripts
tests/               # Regression, isolation and Phase 1 tests
```

## Legacy compile and download

`POST /sessions/{id}/compile` returns 202 and starts the preserved legacy compile workflow. Poll `GET /sessions/{id}/files` until a file with `status="ready"` appears, then use `GET /files/{id}/download`.

Phase 1 project exports use `POST /projects/{id}/exports` and the durable PostgreSQL worker. Poll `GET /projects/{id}/exports` and `GET /projects/{id}/jobs`.

## Health and readiness

- `GET /healthz` — API liveness only.
- `GET /readyz` — database, Alembic head, worker heartbeat, stuck jobs, storage/disk, LibreOffice/font stack and production email readiness.

Production deployment must require `/readyz`, not only `/healthz`.

## Running tests

Tests run against a separate PostgreSQL database (port 5433 in `docker-compose.yml`):

```bash
docker-compose up -d postgres-test
pytest -v

# Fast Phase 1 contract tests
pytest tests/test_phase1_unit.py -v

# Critical user-isolation tests
pytest tests/test_isolation.py -v
```

GitHub Actions also performs an Alembic `head → 0006 → head` round trip, frontend JavaScript syntax validation, Phase 1 tests and the full regression suite.

## Deployment

Production deploys to the Oracle Cloud VM hosting `robofox.online`:

```bash
scripts/deploy_to_oracle.sh
```

The deployment script installs missing runtime packages, creates swap when needed, upgrades the schema, starts/reloads both `thesis-api` and `thesis-worker`, and fails unless `/readyz` passes.

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

## Working with coding agents

The repo includes `CLAUDE.md` with standing implementation and safety instructions. Keep Phase 1 changes on an isolated branch and do not deploy or merge until migration, Phase 1 and full regression checks pass.

## Documentation

- `docs/PHASE1_TRUSTED_CONVERSION.md` — Phase 1 architecture, operator workflow, deployment and rollback.
- `CLAUDE.md` — standing coding-agent instructions.
- `app/formatter/SKILL.md` (when present) — legacy thesis format specification.
- `/docs` with `DEBUG=true` — OpenAPI documentation.

## Stack

- Python 3.11, FastAPI, SQLAlchemy 2.0 async, PostgreSQL 14+
- Alembic migrations and PostgreSQL-backed durable job queue
- Anthropic/Claude legacy coaching and compile integration
- Cloudflare R2 or local storage
- Resend transactional email
- python-docx and LibreOffice for governed Word/PDF rendering
