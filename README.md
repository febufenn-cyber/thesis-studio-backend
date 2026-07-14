# Acadensia

Acadensia is a FastAPI/PostgreSQL academic-document platform built around five governed layers:

1. **Trusted manuscript conversion** — preserve, inspect, parse, verify and export an uploaded thesis without silent content loss.
2. **Human review and editing** — correct the canonical thesis through typed, reversible and versioned commands.
3. **Grounded AI thesis partner** — inspect, challenge and propose changes without acquiring authorship, verification or approval authority.
4. **Collaborative academic workspace** — separate student, supervisor, operator, department and examiner powers through review snapshots and institutional policy.
5. **Commercial reliability, security and scale** — enforce editions, billing, revocable sessions, provider routing, recovery, privacy and audited operations.

The preserved legacy coaching interface remains available at `/legacy`. The structured workspace is served at `/`.

## Current release identity

- Application version: `0.7.0`
- Database schema: `0018`
- Canonical schema: versioned independently inside project JSON
- Production release source: an exact commit reachable from `main` with a durable file at `release-candidates/<sha>.json`

A merged commit is not automatically production-ready. See [Release Candidate Hardening](docs/RELEASE_CANDIDATE_HARDENING.md).

## Local development

```bash
git clone https://github.com/febufenn-cyber/thesis-studio-backend.git
cd thesis-studio-backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

docker compose up -d postgres
alembic upgrade head

# Terminal 1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2
python -m app.services.job_queue
```

Create the initial institution when required:

```bash
python scripts/create_institution.py \
  --name "Madras Christian College (Autonomous)" \
  --short-name MCC \
  --domains "mcc.edu.in,students.mcc.edu.in" \
  --address "Tambaram, Chennai – 600 059." \
  --short-address "Tambaram, Chennai – 59" \
  --university "University of Madras" \
  --department "PG & Research Department of English" \
  --aided
```

Open:

- Workspace: `http://localhost:8000/`
- Legacy coaching: `http://localhost:8000/legacy`
- OpenAPI in debug mode: `http://localhost:8000/docs`
- Liveness: `/healthz`
- Readiness: `/readyz`
- Component status: `/status`
- Release identity: `/meta/release`

## Phase 1 — Trusted manuscript conversion

Phase 1 provides:

- immutable original uploads and revisions;
- SHA-256 checksums and parser provenance;
- DOCX type, ZIP-bomb and package validation;
- configurable ClamAV malware scanning before DOCX parsing;
- stable chapter/front-matter/block UUIDs;
- unsupported-object reporting;
- conservative citation resolution;
- source and quotation registries;
- verification-gated final exports;
- clearly labelled review exports;
- DOCX/PDF post-render QA and chain-of-custody manifests.

See [PHASE1_TRUSTED_CONVERSION.md](docs/PHASE1_TRUSTED_CONVERSION.md).

## Phase 2 — Human review and editing

Phase 2 provides:

- three-pane thesis review cockpit;
- lazy chapter loading and stable deep links;
- typed block editing for paragraphs, headings, quotations, verse and markers;
- insert, delete, duplicate, move, convert, split and merge commands;
- optimistic concurrency and idempotent autosave;
- append-only commands with undo/redo;
- checkpoints, snapshot comparison and restore;
- persistent review issues and deterministic readiness;
- original-versus-current comparison;
- template-driven metadata and source forms;
- exact citation-occurrence resolution;
- cached authoritative PDF preview;
- stale preview/export visibility and browser draft recovery.

See [PHASE2_HUMAN_REVIEW.md](docs/PHASE2_HUMAN_REVIEW.md).

## Phase 3 — Grounded AI thesis partner

The canonical Project is the sole source of truth. AI follows this authority path:

```text
bounded project context
→ strict structured output
→ inert proposal
→ human selects/edits operations
→ Phase 2 command engine
→ version/invalidation checks
→ deterministic verification
```

Task modes include understanding, diagnosis, planning, transformation, challenge, research strategy, coherence, viva preparation and memory refresh.

AI cannot directly edit canonical JSON, verify evidence, approve chapters, trigger submission, change institution templates, claim browsing, invent quotations, grade the thesis or assist AI-detection evasion. Direct quotation insertion requires an already human-verified quote registry ID.

See [PHASE3_GROUNDED_AI.md](docs/PHASE3_GROUNDED_AI.md).

## Phase 4 — Collaborative academic workspace

Phase 4 provides:

- verified institution and department memberships;
- capability-based project access;
- separate metadata, content, sources and private-AI-history permissions;
- immutable review snapshots and repeated review cycles;
- anchored comments and structured human suggestions;
- student-controlled suggestion acceptance;
- separate content, citation, formatting, institutional and submission approvals;
- dependency-aware approval invalidation;
- supervisor instructions and role-specific queues;
- versioned institutional profiles, policies and official templates;
- sealed submission packages and attestations;
- recipient-bound external examiner access;
- notification, retention, support-access and audit workflows.

Students remain authors, supervisors remain reviewers, operators remain formatters and AI remains an assistant.

## Phase 5 — Commercial reliability, security and scale

Phase 5 adds:

- student, operator and institution product editions;
- backend entitlement enforcement and usage/cost ledgers;
- signed, idempotent and tenant-bound billing events;
- revocable server-side application sessions;
- provider-neutral AI routing and circuit breakers;
- separate general, AI, PDF and maintenance worker queues;
- expiring job leases and crash recovery;
- release, incident, SLO, backup and restore records;
- versioned privacy notices, consent and data inventory;
- policy-driven retention/deletion and sealed-custody controls;
- metadata-only support diagnostics;
- exact release identity and component status;
- immutable image, canary and rolling deployment workflow.

See:

- [Commercial operating contract](PHASE5-COMMERCIAL-OPERATING-CONTRACT.md)
- [Production topology](docs/phase5/production-topology.md)
- [Security verification matrix](docs/phase5/security-verification-matrix.md)
- [Incident runbook](docs/runbooks/incident-response.md)
- [Backup/restore runbook](docs/runbooks/backup-restore.md)

## Release candidate workflow

Every pull request to `main` and every non-attestation push to `main` runs `.github/workflows/main-release-candidate.yml`:

- Python compilation and application import;
- all workspace JavaScript syntax checks;
- Alembic `head → 0016 → head` verification;
- dependency, Bandit and tracked-file secret-pattern gates;
- complete Phase 1–5 regression/acceptance suite;
- immutable Docker image build;
- exact-commit evidence artifact.

A successful `main` push produces `release-candidates/<sha>.json`. The manual release workflow refuses SHAs that:

- are not reachable from `main`;
- lack the matching attestation;
- contain test failures/errors;
- lack a successful image-build result.

Deployment remains manual and protected by GitHub environments. It performs target environment validation, staging/canary smoke tests and production backup-evidence checks.

## Required pre-production evidence

Before broad production launch, complete:

- [Staging acceptance](docs/release/STAGING_ACCEPTANCE.md)
- [Real manuscript pilot](docs/release/REAL_MANUSCRIPT_PILOT.md)
- [Institution profile sign-off](docs/release/INSTITUTION_PROFILE_SIGNOFF.md)
- [Restore drill evidence](docs/release/RESTORE_DRILL_EVIDENCE.md)
- [Release decision](docs/release/RELEASE_DECISION.md)

These documents do not manufacture external proof. Qualified legal/accounting review, institution approval, production credentials, independent security assessment and observed operational history remain external gates.

## Production topology

The release compose file runs:

- `web-a` and `web-b`;
- `worker-general`;
- `worker-ai`;
- `worker-pdf`;
- `maintenance`;
- internal health-checked ClamAV.

Production PostgreSQL must be external to the application host. Durable objects use Cloudflare R2. Both application and ClamAV images must be pinned to immutable references. Place web instances behind health-aware routing.

```bash
python scripts/verify_phase5_environment.py --target staging
python scripts/phase5_smoke.py --base-url https://staging.example --expected-release <sha>
```

The production release workflow is `workflow_dispatch` only; it never runs on push and never enables auto-merge.

## Testing

```bash
pytest -q
pytest -q tests/test_release_candidate_hardening.py
python scripts/check_secret_patterns.py
python scripts/run_phase3_evals.py
python -m compileall -q app tests scripts
node --check app/static/phase2-core.js
node --check app/static/phase2-editor.js
node --check app/static/phase2-review.js
node --check app/static/phase2-integrity.js
node --check app/static/phase3-ai.js
node --check app/static/phase4-collaboration.js
```

## Project structure

```text
app/
├── ai/              # bounded AI context, provider adapters, proposals and evaluations
├── api/             # auth, projects, editor, AI, collaboration and commercial APIs
├── canonical/       # stable canonical thesis model and JSON migrations
├── collaboration/   # capabilities and institutional workflow rules
├── commercial/      # entitlements, billing, sessions, recovery, privacy and support
├── editor/           # deterministic command engine
├── ingest/           # malware/package preflight, parsing and verification
├── models/           # SQLAlchemy models
├── renderers/        # governed DOCX/PDF/Markdown/Text renderers
├── services/         # jobs, preview, export, storage, readiness and email
└── static/           # review, AI and collaboration workspace

deploy/              # release compose topology
docs/release/         # launch evidence templates
docs/runbooks/        # incident, restore and support procedures
release-candidates/   # workflow-generated exact-main validation attestations
```

## Explicit non-claims

The repository does not by itself establish an uptime SLA, zero data loss, legal digital signatures, GST/tax correctness, DPDP compliance, ASVS/SOC 2/ISO certification, 24/7 staffed support, institution approval or a completed independent penetration test.
