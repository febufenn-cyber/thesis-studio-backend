# CLAUDE.md — Robofox Thesis Studio Backend

This file is read by Claude Code at the start of every session in this repo. It encodes the standing rules and context so we don't waste turns re-explaining.

## What this project is

A FastAPI backend powering **Robofox Thesis Studio**, a web app that guides MA students through writing their dissertations using Claude. Students log in with their institutional email, chat with a thesis-coaching AI, and compile a formatted Word document at the end.

The frontend (Next.js) lives in a separate repo: `thesis-studio-frontend`. This repo is backend-only.

## Stack (do not change without asking)

- **Language:** Python 3.11
- **Web framework:** FastAPI (async)
- **ORM:** SQLAlchemy 2.0 (async, with asyncpg driver)
- **Migrations:** Alembic
- **Database:** PostgreSQL 14+ (uses no version-specific features)
- **LLM:** Anthropic Claude API via the `anthropic` Python SDK
- **Document generation:** `python-docx` (already built — see `app/formatter/`, treat as a black box)
- **File storage:** Cloudflare R2 (S3-compatible, via `boto3`)
- **Email:** Resend (via HTTP API)
- **Auth:** Magic-link with JWT cookies
- **Process manager:** PM2 (production)
- **Reverse proxy:** Nginx (production)

## Deployment target

Oracle Cloud VM (Ubuntu 22.04, public IP `68.233.116.11`, Hyderabad region). Subdomain: `thesis-api.robofox.online`. The same VM runs `api.robofox.online` (LeadFinder) and `robofox.online` (marketing site). Don't break those.

Deploy workflow: local edits → git push → SSH to VM → git pull → `pm2 restart thesis-api`.

## What's already built (don't touch unless explicitly asked)

The `app/formatter/` directory contains a tested document-generation pipeline:

- `thesis_formatter.py` — produces MLA-compliant .docx files matching MCC / University of Madras format. 1.5"L / 1"T-R-B margins, TNR 12pt, 1.5 line spacing, two-column certificate signature block, hanging-indent works cited.
- `inline_markdown.py` — parses `*foo*` markers in body text into italicized runs. Used by the formatter for MLA work-title italicization.
- `prompts.py` — the production system prompts (`COACHING_BASE_PROMPT`, `build_coaching_system_blocks()`, `COMPILE_SYSTEM_PROMPT`).
- `compile_pipeline.py` — calls Claude with the compile prompt, parses the JSON, renders the .docx.

These were verified end-to-end against a real MCC reference thesis. **Do not modify them** unless I explicitly ask. Use them as imports.

## Hard rules

### Per-user isolation is non-negotiable

Every endpoint that touches user-owned data MUST:

1. Extract `current_user` from the JWT (use `Depends(get_current_user)` from `app/api/deps.py`).
2. Filter every query by `user_id = current_user.id`.
3. Return **404** (not 403) when a user tries to access another user's resource. 403 leaks resource existence; 404 is opaque.

There's a test in `tests/test_isolation.py` that creates two users and tries to access each other's sessions. **It must pass on every commit.** If you change auth or session code, run that test.

### Never log secrets

Don't log `Authorization` headers, JWT tokens, API keys, or full `messages[]` arrays. Truncate user content to first 100 chars in logs.

### Never bypass auth in production code

If you need to call an endpoint without auth for testing, use the test fixtures in `tests/conftest.py`. Don't add `if settings.DEBUG:` bypasses anywhere.

### Database: async only

This project uses SQLAlchemy 2.0 async. **Don't write sync queries.** All `db.execute()` calls are awaited. All routes that touch the DB are `async def`.

### Every Claude call records a usage_events row

Every call to Claude records a row in `usage_events` with `input_tokens`, `output_tokens`, `cached_input_tokens`, `model`, and `estimated_cost_usd`. Under Max+CLI the cost is notional (Max is flat-rate, not per-call), but the row is still useful for relative comparisons across calls and as an operational audit trail.

### Auth: Claude Code CLI subprocess with Max OAuth

Claude calls go through the Claude Code CLI (`claude -p ...`) as a subprocess from `app/services/claude_service.py`. The CLI handles its own OAuth state — log in once per host with `claude /login`. `ANTHROPIC_API_KEY` in `.env` is unused at runtime; a non-empty placeholder satisfies the Settings min_length check.

### Do not switch the chat path to `--continue` / `--resume`

The chat subprocess deliberately uses `--no-session-persistence` and embeds prior turns into each user prompt via `ClaudeService._format_conversation`. Reasons:

- Our session of record is the `sessions` + `messages` rows in Postgres, owned per-user. `--continue`/`--resume` would introduce a parallel Claude-Code-managed session store on disk and require synchronizing UUIDs across the two stores.
- Cross-store sync would also bypass per-user isolation (the on-disk sessions aren't owned by anyone in our model).
- Embedded history is stateless, debuggable from the DB, and survives restarts of the CLI.

If you find yourself reaching for `--continue` to "fix" multi-turn behavior, the right move is to improve the formatting in `_format_conversation`, not to introduce session-store sync.

## Model rules

- **Default model:** `claude-sonnet-4-5` for chat. `claude-opus-4-7` only for the compile pass. `claude-haiku-4-5-20251001` for utility calls (titles, intent classification). Pass full model IDs to the CLI, not aliases like `sonnet` (the alias resolves to whatever the latest Sonnet is).
- **Per-user monthly token caps are disabled.** All sessions share the one Max account's 5-hour rate limit; per-user enforcement isn't meaningful when the upstream constraint is shared. The `USER_MONTHLY_*_TOKEN_CAP` settings are kept for forward-compat but no middleware reads them.

## Conventions

### Imports

Standard library first, third-party second, local third. Within each group, alphabetical.

```python
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.session import Session
```

### Type hints

Required on every function signature. Use `from __future__ import annotations` at the top of every file so `list[Foo]` works without `List` import.

### Error handling

Raise `HTTPException` from route handlers. Convert ORM-level exceptions to HTTP responses in `app/core/exceptions.py` global handlers. Don't catch broad `Exception` in route handlers.

### Docstrings

Triple-quoted, one-line summary then optional details. Required on all service-layer functions and route handlers.

### Tests

`pytest` with `pytest-asyncio`. Each test gets a fresh DB transaction that rolls back at the end (see `conftest.py` `db_session` fixture). Tests must be independent — no shared state.

## Don't do this

- **Don't introduce new dependencies** without checking with me. Every new dep is a security and maintenance burden.
- **Don't write to disk in route handlers** except via the storage service (`app/services/storage_service.py`).
- **Don't use sync `requests`** anywhere. Use `httpx.AsyncClient`.
- **Don't disable Pydantic strict mode.** Schemas are the API contract.
- **Don't commit `.env`** files. The `.gitignore` already excludes them but double-check.
- **Don't make the JWT secret short or guessable.** It's loaded from env, generated with `openssl rand -hex 32`.

## Known issues

- **`tests/conftest.py` per-test transaction isolation is broken.** 11 of 14 tests error in the fixture (not in app code) due to a `join_transaction_mode` issue: the outer transaction isn't `create_savepoint`-wrapped, so handler `commit()` calls desync the connection ("another operation is in progress"). The 2 tests that pass don't exercise the handler-commit path, so they're not a meaningful gate. **Smoke test (curl against the dev server) is the current integration gate.** Fix conftest before any deploy that adds real users — the isolation contract matters too much to ship without working tests.

## Build phases (current state)

- [x] Phase 1: Foundations — auth, DB schema, magic link login
- [ ] Phase 2: Chat core — sessions, messages, SSE streaming, prompt caching
- [ ] Phase 3: Compile and download — docx generation, R2 upload, signed URLs
- [ ] Phase 4: Polish — usage caps, admin dashboard, onboarding flow

When working on a phase, focus on it. Don't sprawl into the next phase before the current one is solid and tested.

## Useful commands

```bash
# Install deps
pip install -r requirements.txt

# Run dev server (auto-reload)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
pytest -v

# Run only the isolation test (the critical one)
pytest tests/test_isolation.py -v

# Create a new migration after model changes
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Add a new institution
python scripts/create_institution.py --name "Madras Christian College" --domain "mcc.edu.in"

# Local Postgres (for development)
docker-compose up -d postgres
```

## Environment variables

See `.env.example` for the full list. Required for the app to boot:

- `DATABASE_URL` — `postgresql+asyncpg://user:pass@host/dbname`
- `JWT_SECRET` — 64-char hex string
- `ANTHROPIC_API_KEY` — from console.anthropic.com (institutional grant key)
- `RESEND_API_KEY` — for sending magic-link emails
- `R2_*` — Cloudflare R2 credentials and bucket
- `FRONTEND_URL` — for CORS and magic-link redirects
- `DEFAULT_INSTITUTION_SHORT_NAME` — fallback institution for emails not matching any institution's `email_domains` (e.g. `MCC`). Open signup is enabled; domain match is a hint, not a requirement.

## When in doubt

Ask before:
- Changing the database schema (migrations are forever in production)
- Changing auth flow or JWT structure
- Adding a new external service dependency
- Changing the formatter or prompts (they're locked-in deliverables)
- Touching anything in production deployment scripts

Read first:
- The engineering plan in this conversation (it has rationale for choices)
- The `app/formatter/` modules before integrating with them
- The latest commit messages to understand what just changed
