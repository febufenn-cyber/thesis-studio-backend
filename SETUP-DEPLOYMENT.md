# Pre-deploy Setup — Oracle VM Diagnostics + Production `.env`

Read this **before** running `scripts/deploy_to_oracle.sh` for the first time. The deploy script assumes the VM is in one of three known states; this doc tells you which state you're in and what (if anything) to edit in the script.

---

## 1. Diagnose VM state

SSH in and run these. Save the output — you'll match it against outcomes A/B/C below.

```bash
ssh ubuntu@68.233.116.11

# What postgres-* packages are installed
dpkg -l | grep -E '^ii.*postgresql' | awk '{print $2, $3}' || echo "no postgresql packages installed"

# Who's listening on 5432
sudo ss -tlnp 2>/dev/null | grep ':5432' || echo "nothing on :5432"

# What databases exist (only works if postgres is running and you have sudo)
sudo -u postgres psql -l 2>/dev/null | head -20 || echo "postgres not running or no postgres role"

# What other apps live on this VM (looking for LeadFinder + marketing site)
find /opt /home /srv /var/www -maxdepth 4 -name '.env' 2>/dev/null
pm2 list 2>/dev/null || echo "pm2 not installed"
sudo systemctl list-units --type=service --state=running 2>/dev/null | grep -iE 'nginx|node|python|gunicorn|uvicorn|postgres' | head
```

Look at the output and pick the matching outcome below.

---

## 2. Outcomes

### Outcome A — Clean VM (no Postgres, no other Python/Node apps)

`dpkg -l | grep postgresql` returns nothing. `ss -tlnp` shows nothing on `:5432`.

**No edits needed.** Run `scripts/deploy_to_oracle.sh` as-is.

---

### Outcome B — Postgres 16 already running for another app (e.g. LeadFinder)

`dpkg -l | grep postgresql` shows `postgresql-16` as installed. `ss -tlnp` shows postgres listening on `:5432`. `sudo -u postgres psql -l` lists at least one DB (likely `leadfinder` or similar).

**Trust the existing Postgres**; just add our role + DB to it.

In `scripts/deploy_to_oracle.sh`, comment out these two lines (keep everything else):

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git curl ca-certificates build-essential \
    python3.11 python3.11-venv python3.11-dev \
    postgresql-16 postgresql-client-16 \
    >/dev/null
```

→ becomes

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git curl ca-certificates build-essential \
    python3.11 python3.11-venv python3.11-dev \
    >/dev/null
```

(remove the `postgresql-16 postgresql-client-16 \` line)

And:

```bash
echo "[remote] Ensuring Postgres is running"
sudo systemctl enable --now postgresql >/dev/null
```

→ comment out both lines (replace with `:` no-op or a comment).

The "Ensuring Postgres role + database exist" block stays as-is; it uses `sudo -u postgres psql` which works against whichever Postgres cluster is on the socket.

---

### Outcome C — Different Postgres major (e.g. postgresql-14)

`dpkg -l | grep postgresql` shows `postgresql-14` (not 16). The cluster is already running.

Same fix as Outcome B — don't install Postgres 16 alongside (clusters running on different ports gets messy fast). Postgres 14 is fine for our use; we don't depend on Postgres 16-only features.

Comment out the same two sections as Outcome B.

---

### Outcome D — Something else weird (multiple Postgres versions, port 5432 owned by Docker, etc.)

Stop. Don't run the deploy. Reply to me here with the diagnostic output and we'll figure it out together.

---

## 3. Set up the production `.env` on the VM

The deploy script refuses to run if `/opt/thesis-studio-backend/.env` doesn't exist.

### 3a. Copy the template up

From your Mac:

```bash
scp .env.production.example ubuntu@68.233.116.11:/tmp/thesis.env
```

### 3b. SSH in and move it into place

```bash
ssh ubuntu@68.233.116.11
sudo mkdir -p /opt/thesis-studio-backend
sudo mv /tmp/thesis.env /opt/thesis-studio-backend/.env
sudo chown ubuntu:ubuntu /opt/thesis-studio-backend/.env
chmod 600 /opt/thesis-studio-backend/.env
```

`chmod 600` matters — `.env` contains secrets; only the owner should read it.

### 3c. Generate the secrets

```bash
# JWT_SECRET — 64 hex chars
echo "JWT_SECRET=$(openssl rand -hex 32)"

# DB password — strong, no special shell chars
echo "DB_PASS=$(openssl rand -base64 24 | tr -d '+/=' | head -c 32)"
```

Copy both values. You'll paste them into `.env` next.

### 3d. Edit `.env` in place

```bash
sudo nano /opt/thesis-studio-backend/.env
# or: sudo vim /opt/thesis-studio-backend/.env
```

Replace every `CHANGE_ME`:

| Field | Value |
|---|---|
| `JWT_SECRET` | The 64-char hex from step 3c |
| `DATABASE_URL` | Replace `CHANGE_ME` with the DB password from step 3c |
| `RESEND_API_KEY` | From https://resend.com/api-keys (only needed once you want real magic-link emails — leave blank for first-deploy smoke test, links print to pm2 logs) |
| `R2_ACCOUNT_ID` | Cloudflare dashboard → R2 → API Tokens. Optional for chat smoke test; required before compile pass |
| `R2_ACCESS_KEY_ID` | Same |
| `R2_SECRET_ACCESS_KEY` | Same |
| `R2_PUBLIC_URL` | Same |

The DB password you put into `DATABASE_URL` is the same password the deploy script will use when it runs `CREATE ROLE thesis LOGIN PASSWORD '<that password>'`. They must match.

Save, exit.

### 3e. Sanity-check the `.env`

```bash
grep -E '^(JWT_SECRET|DATABASE_URL|ANTHROPIC_API_KEY|CLAUDE_CLI_PATH|DEFAULT_INSTITUTION_SHORT_NAME|FRONTEND_URL|CORS_ORIGINS)=' /opt/thesis-studio-backend/.env
```

Confirm:
- `JWT_SECRET` is 64 hex chars (not `CHANGE_ME_...`)
- `DATABASE_URL` has a real password (not `CHANGE_ME`)
- `ANTHROPIC_API_KEY=sk-ant-placeholder` (this is correct — it's intentionally a placeholder under Max+CLI auth)
- `CLAUDE_CLI_PATH=claude`
- `FRONTEND_URL=https://thesis.robofox.online`
- `CORS_ORIGINS=https://thesis.robofox.online`

---

## 4. Now run the deploy

Back on your Mac, in the repo root:

```bash
scripts/deploy_to_oracle.sh
```

If you edited the script per Outcome B/C, those edits stay local — don't commit them; the script's "clean tree" check would reject the deploy. Either:
- Edit the script, run it, then `git checkout scripts/deploy_to_oracle.sh` to revert
- Or set `DEPLOY_SKIP_POSTGRES_INSTALL=1` and add a one-line guard in the script (cleaner; consider for a future commit)

After the script reports `pm2 status: online` for `thesis-api`, follow the next-steps printed at the end (one-time `claude /login` on the VM, then `pm2 restart thesis-api`).

Then: open `SETUP-CLOUDFLARE-TUNNEL.md` and continue with the tunnel + Access setup.
