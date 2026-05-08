# Robofox Thesis Studio — Backend

FastAPI backend for the Robofox Thesis Studio web app. AI-guided MA thesis writing for graduate students, powered by Claude.

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
#   ANTHROPIC_API_KEY (from console.anthropic.com)

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

# 6. Run the dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Visit `http://localhost:8000/docs` for the interactive API docs (only enabled when `DEBUG=true`).

## Project structure

```
app/
├── api/             # Route handlers (auth, sessions, chat, compile)
├── core/            # Settings, JWT, security helpers
├── db/              # SQLAlchemy engine, session factory, deps
├── models/          # ORM models (one file per table)
├── schemas/         # Pydantic request/response shapes
├── services/        # External integrations (Claude, email, R2)
├── formatter/       # Thesis document generation (verified — don't modify)
└── main.py          # FastAPI app entry point

migrations/          # Alembic migrations
scripts/             # Operational scripts (institution bootstrapping)
tests/               # Pytest suite — test_isolation.py is critical
```

## Running tests

Tests run against a separate Postgres database (port 5433 in docker-compose):

```bash
docker-compose up -d postgres-test
pytest -v

# Run only the critical isolation tests
pytest tests/test_isolation.py -v
```

## Deployment

Production deploys to the Oracle Cloud VM that hosts `robofox.online`:

```bash
ssh robofox-vm
cd /opt/thesis-studio-backend
git pull
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
pm2 restart thesis-api
```

The Nginx config for `thesis-api.robofox.online` proxies to `localhost:8000`.

## Working with Claude Code

This repo includes a `CLAUDE.md` file at the root with standing instructions. Open the repo in Cursor and start a Claude Code session — it will read the standing instructions and pick up project conventions automatically.

## Documentation

- `CLAUDE.md` — standing instructions for Claude Code sessions
- `app/formatter/SKILL.md` (when copied here) — thesis format spec
- `/docs` (when running with `DEBUG=true`) — interactive OpenAPI docs

## Stack

- Python 3.11, FastAPI, SQLAlchemy 2.0 async, PostgreSQL 16
- Anthropic Claude API (Sonnet 4.6 chat, Opus 4.7 compile, Haiku 4.5 utility)
- Cloudflare R2 for file storage
- Resend for transactional email
- python-docx for Word document generation
