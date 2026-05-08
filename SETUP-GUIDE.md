# Robofox Thesis Studio — Backend Setup Cheat-Sheet

You just downloaded `thesis-studio-backend.tar.gz`. Here's the path from zero to running.

---

## Local development setup (~10 minutes)

### 1. Extract and enter

```bash
tar -xzf thesis-studio-backend.tar.gz
cd thesis-studio-backend
```

### 2. Initialize the git repo

```bash
git init
git add -A
git commit -m "Initial commit: backend skeleton"

# When ready, create the GitHub repo and push:
gh repo create robofox/thesis-studio-backend --private --source=. --push
# Or manually:
# git remote add origin git@github.com:robofox/thesis-studio-backend.git
# git push -u origin main
```

### 3. Python environment

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
JWT_SECRET=$(openssl rand -hex 32)              # paste this in
ANTHROPIC_API_KEY=sk-ant-...                    # from console.anthropic.com
DATABASE_URL=postgresql+asyncpg://thesis:thesis@localhost:5432/thesis_studio
```

For local dev only, you can leave `RESEND_API_KEY` blank — magic-link URLs print to the console instead of being emailed.

### 5. Start Postgres

```bash
docker-compose up -d postgres
```

### 6. Run migrations

```bash
alembic upgrade head
```

This creates all 7 tables: `institutions`, `users`, `auth_tokens`, `sessions`, `messages`, `files`, `usage_events`.

### 7. Bootstrap your first institution

```bash
python scripts/create_institution.py \
    --name "Madras Christian College (Autonomous)" \
    --short-name "MCC" \
    --domains "mcc.edu.in,students.mcc.edu.in" \
    --address "Tambaram, Chennai – 600 059." \
    --short-address "Tambaram, Chennai – 59" \
    --university "University of Madras" \
    --department "PG & Research Department of English" \
    --aided
```

Now any email at `mcc.edu.in` or `students.mcc.edu.in` can sign up.

### 8. Run the dev server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs` to see all endpoints with the interactive Swagger UI.

### 9. Smoke test the auth flow

```bash
# Request a magic link
curl -X POST http://localhost:8000/auth/request-link \
  -H "Content-Type: application/json" \
  -d '{"email":"yourname@mcc.edu.in"}'

# Watch the uvicorn console — it will log the magic link URL.
# Paste it into the browser. You'll be redirected with an auth cookie set.
```

---

## Run the test suite

The critical one is `test_isolation.py` — it verifies the per-user security boundary.

```bash
# Start the test database (in-memory, port 5433)
docker-compose up -d postgres-test

# Point tests at it
export DATABASE_URL=postgresql+asyncpg://thesis:thesis@localhost:5433/thesis_studio_test

# Run all tests
pytest -v

# Run only the isolation tests
pytest tests/test_isolation.py -v
```

You should see all tests pass. If `test_isolation.py` ever fails, do not deploy — the security boundary is broken.

---

## Production deployment to Oracle Cloud VM

This is the deploy procedure once the app is ready for staging/production.

### One-time VM setup

```bash
ssh root@68.233.116.11

# Postgres (use the same VM)
apt install -y postgresql postgresql-client
sudo -u postgres createuser thesis -P     # set password, save it
sudo -u postgres createdb thesis_studio -O thesis

# Python
apt install -y python3.11 python3.11-venv

# App directory
mkdir -p /opt/thesis-studio-backend
cd /opt/thesis-studio-backend
git clone git@github.com:robofox/thesis-studio-backend.git .

python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Production .env
cp .env.example .env
# Edit .env with production values:
#   ENV=production
#   DEBUG=false
#   DATABASE_URL=postgresql+asyncpg://thesis:<password>@localhost:5432/thesis_studio
#   JWT_SECRET=<openssl rand -hex 32>
#   ANTHROPIC_API_KEY=<institutional grant key>
#   RESEND_API_KEY=<from resend.com>
#   R2_*=<from cloudflare>
#   FRONTEND_URL=https://thesis.robofox.online
#   CORS_ORIGINS=https://thesis.robofox.online
#   ALLOWED_EMAIL_DOMAINS=mcc.edu.in,students.mcc.edu.in

# Migrate
alembic upgrade head

# Bootstrap the institution
python scripts/create_institution.py --name "..." ...

# PM2
pm2 start "venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000" --name thesis-api
pm2 save
pm2 startup    # follow the printed instructions to enable on boot
```

### Nginx config for `thesis-api.robofox.online`

`/etc/nginx/sites-available/thesis-api.robofox.online`:

```nginx
server {
    listen 443 ssl http2;
    server_name thesis-api.robofox.online;

    ssl_certificate /etc/letsencrypt/live/thesis-api.robofox.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/thesis-api.robofox.online/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE streaming — these matter
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}

server {
    listen 80;
    server_name thesis-api.robofox.online;
    return 301 https://$host$request_uri;
}
```

```bash
ln -s /etc/nginx/sites-available/thesis-api.robofox.online /etc/nginx/sites-enabled/
certbot --nginx -d thesis-api.robofox.online
nginx -t && systemctl reload nginx
```

### Routine deploys

```bash
ssh root@68.233.116.11
cd /opt/thesis-studio-backend
git pull
source venv/bin/activate
pip install -r requirements.txt   # only if requirements changed
alembic upgrade head              # only if migrations changed
pm2 restart thesis-api
pm2 logs thesis-api --lines 50    # confirm clean start
```

---

## Working with Cursor + Claude Code on this repo

Open the repo in Cursor. Start a Claude Code session.

The `CLAUDE.md` file at the repo root tells Claude Code:
- The full stack and conventions
- What's already built and is locked-in (the formatter, the prompts)
- The hard rules (per-user isolation, async-only, every Claude call records usage)
- The current build phase
- Useful commands

Your first prompt to Claude Code should be something like:

> Read CLAUDE.md and summarize where this project stands, then suggest the next thing to build.

Claude Code will read it, propose the next piece, and you can direct from there. Good first targets after this skeleton:

1. **Compile endpoint** (`POST /sessions/{id}/compile`). Wires the existing `compile_pipeline.py` into a route that returns a download URL. Needs the R2 storage service first.
2. **Storage service** (`app/services/storage_service.py`). Wraps boto3 for R2 uploads and signed URL generation.
3. **Usage cap middleware**. Reject requests when a user exceeds the monthly token cap. Query `usage_events` summed for current month per user.
4. **Admin endpoints** (`/admin/usage`, `/admin/institutions`). Behind an `is_admin` flag on User.
5. **Next.js frontend**. Separate repo. The chat UI consuming the SSE stream is the hardest piece; the rest is straightforward.

---

## Troubleshooting

**App fails to boot with "JWT_SECRET is still the placeholder"**: Run `openssl rand -hex 32` and paste the output into `.env`.

**Migrations fail with "permission denied"**: The Postgres user needs ownership of the database. As Postgres superuser: `ALTER DATABASE thesis_studio OWNER TO thesis;`

**SSE responses look choppy**: Verify Nginx has `proxy_buffering off` for the API location.

**Magic link emails not arriving**: Check the uvicorn/PM2 logs for the line "RESEND_API_KEY not set". You probably haven't configured Resend yet — for production you must.

**Tests can't connect to the test DB**: Make sure `docker-compose up -d postgres-test` is running and `DATABASE_URL` in your shell points at port 5433 (not 5432).

**"AssertionError: Status code 204 must not have a response body"**: Already fixed in this skeleton, but if you hit this on a new endpoint, add `response_class=Response` to the route decorator and explicitly return `Response(status_code=204)`.

---

## What's NOT in this skeleton (build next)

- `app/api/compile.py` — the compile endpoint (use `compile_pipeline.py` from `app.formatter`)
- `app/services/storage_service.py` — R2 boto3 wrapper for file uploads
- Usage cap enforcement middleware
- Admin endpoints (institution CRUD, usage reports)
- The Next.js frontend (separate repo)
- Per-month token-cap aggregation queries (the schema supports it; just not wired into a check yet)

The skeleton has everything needed for the auth + chat loop. Ship that to a few test students first; the rest can follow.
