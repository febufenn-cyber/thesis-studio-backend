# Staging PostgreSQL Specification — Robofox Thesis Studio

Date: 2026-07-12 · Target release: main `b2c9c624cd6b6faffe4f9585ac7f4580631abd82`
Scope: the **isolated staging PostgreSQL** required by
`docs/release/staging/STAGING_PROVISIONING.md` §3 and
`docs/phase5/production-topology.md` boundary 1 ("PostgreSQL must not run on
the application host"). Staging app host: OCI `VM.Standard.A1.Flex` (ARM64) in
`ap-hyderabad-1` — the release image is multi-arch (`linux/amd64` +
`linux/arm64`, built and manifest-verified by `phase5-release.yml`), so the
old amd64-only constraint no longer applies. Fixed decisions inherited:
`AI_GLOBAL_ENABLED=false`, `BILLING_PROVIDER=manual`, tunnel-only ingress,
**no production changes**, **no credentials in this document** — every
owner-specific value is `CHANGE_ME`.

## 1. Requirements this spec must satisfy

PostgreSQL 16. TLS required on every application connection. Staging-only
credentials (never shared with production, LeadFinder, or the marketing site).
Network access restricted to the staging app VM — no public unrestricted
ingress on 5432. Automated backups to the staging R2 bucket (`backups/`
prefix, 30-day lifecycle per `deploy/r2-lifecycle-staging.json`). PITR where
the platform provides it (honest gaps documented below). Connection limits
sized from the app's real pool settings. Encrypted storage at rest. Basic
monitoring. Internal recovery targets from `docs/runbooks/backup-restore.md`:
RPO 15 minutes / RTO 2 hours — targets, not yet demonstrated.

## 2. Options for a solo operator in/near ap-hyderabad-1 (honest comparison)

| Option | Cost | Latency from Hyderabad app VM | Connection limits | Backups / PITR | Deal-breakers and caveats |
|---|---|---|---|---|---|
| **(a) Second OCI A1 slice, self-managed PG16** | ₹0 within Always Free — but the free budget is **4 OCPU / 24 GB total, shared with the app VM**. Realistic split: app VM 3 OCPU / 18 GB, DB VM 1 OCPU / 6 GB. 200 GB total free block storage also shared. | Sub-millisecond (same VCN, private subnet) | You set `max_connections` (this spec: 220) | You build everything: nightly `pg_dump` to R2 out of the box; true PITR only if you add pgBackRest/WAL-G WAL archiving | You are the DBA: patching, TLS, `pg_hba`, disk alerts. A1 capacity in ap-hyderabad-1 is frequently "out of capacity" — instance creation may take retries/days. 1 OCPU / 6 GB is ample for staging load but nothing else fits in the free budget afterwards. |
| **(b) Neon free tier** | $0 | No India region as of writing — nearest is AWS ap-southeast-1 (Singapore), ~40–75 ms RTT **per round trip**; check whether an Azure India region exists when you sign up | Direct `max_connections` scales with compute: ~112 at 0.25 CU (free ceiling) — **below the app's 180-connection worst case** (§9). Pooled endpoint is PgBouncer in transaction mode, which conflicts with asyncpg's prepared statements | Branching-based restore window ~6 h on free (verify current limits at signup) | ~190 compute-hours/month and **autosuspend after ~5 min idle**: cold starts add ~0.5–5 s to the first query, which will trip `/readyz`-based smoke checks intermittently. 512 MB storage cap. Free tier limits change often — verify all numbers at signup. |
| **(b') Neon paid "Launch" (~US$19/mo)** | ~US$19/mo (verify) | Same region caveat as free | ≥0.5 CU sustains ~225 direct connections — clears the 180 worst case | ~7-day point-in-time restore, managed backups | The defensible managed pick if you refuse to operate PG yourself. Every query still pays the Singapore RTT; acceptable for staging correctness testing, misleading for staging *performance* numbers. |
| **(c) Supabase free tier** | $0 | Mumbai region (aws ap-south-1) exists — good latency (~15–30 ms) | Micro instance: ~60 direct connections — **far below the 180 worst case**. Direct connection is IPv6-only (IPv4 costs extra); Supavisor pooler: port 5432 = session mode (asyncpg-compatible), port **6543 = transaction mode — do not use**: asyncpg/SQLAlchemy rely on session state and prepared statements | Daily backups on paid; minimal on free | **Projects pause after ~7 days of inactivity — fatal.** A paused staging DB fails `/readyz`, the smoke test, and any UAT run that starts after a quiet week. Postgres 15/16 depending on project vintage. 500 MB DB cap. Not defensible for standing staging. |
| **(d) Aiven free / cloud trials** | $0 (free) or credits | Free-plan regions are limited (no India as of writing) | Free plan ~1 CPU / 1 GB / 5 GB single node | No PITR on free; trials expire | Trials ($300-ish credits, 30 days) are a cliff, not a plan. Fine for a one-week experiment, wrong for a staging environment that must exist for months. OCI's own managed "Database with PostgreSQL" has **no free tier** (tens of USD/month minimum). |

**Recommendation.** Primary: **(a) self-managed PG16 on a second A1 slice** in
the same VCN — zero marginal cost, sub-ms latency, full control of
`max_connections`, and the restore drill runs against it without provider
quirks. Fallback if you refuse to operate PostgreSQL: **(b') Neon paid
Launch** — accept the Singapore RTT and the subscription. **Rejected:**
Supabase free (pausing breaks readiness), Neon free (autosuspend cold starts +
112-connection ceiling), trials (expiry cliff). The rest of this spec encodes
option (a); §13 notes the deltas if you pick Neon.

## 3. Required PostgreSQL extensions — verified finding

Checked 2026-07-12 against this repo:

```bash
grep -rniE "create extension" migrations/    # → no matches
```

**No extension is required.** The only non-default-looking function in any
migration is `gen_random_uuid()` (`migrations/versions/0017_phase5_commercial_reliability.py`),
which is **core PostgreSQL since v13** — no `pgcrypto` needed on PG16.
Application UUIDs are otherwise generated in Python (`uuid4()`). Optional,
ops-only: `pg_stat_statements` (contrib, ships with `postgresql-16`) for
normalized query monitoring — recommended precisely because it stores
*normalized* statements, so thesis prose in JSONB `INSERT` literals never
lands in monitoring output (data-map rule 1).

## 4. DB VM provisioning (option a)

No public IP if you can operate via the app VM as jump host; if you need
direct SSH, a public IP with NSG-restricted port 22 is the pragmatic solo
fallback. **Never** open 5432 to `0.0.0.0/0` in either case.

```bash
OCI_CLI_AUTH=security_token oci compute instance launch \
  --availability-domain CHANGE_ME_AD --compartment-id CHANGE_ME_COMPARTMENT_OCID \
  --shape VM.Standard.A1.Flex --shape-config '{"ocpus":1,"memoryInGBs":6}' \
  --image-id CHANGE_ME_UBUNTU_2204_AARCH64_IMAGE_OCID \
  --display-name thesis-staging-db --subnet-id CHANGE_ME_SUBNET_OCID \
  --assign-public-ip false \
  --ssh-authorized-keys-file CHANGE_ME_STAGING_ONLY_PUBKEY
```

Honest free-tier accounting: this 1 OCPU / 6 GB slice plus a 3 OCPU / 18 GB
app VM exactly exhausts the Always Free A1 budget (4 OCPU / 24 GB). Boot
volumes (min ~47 GB each) draw from the shared 200 GB free block-storage
budget — two VMs ≈ 94–100 GB, leaving little for growth. OCI block volumes
are **encrypted at rest by default** (Oracle-managed keys), which satisfies
the encrypted-storage requirement with no extra work.

Install PostgreSQL 16 (Jammy ships PG14; use PGDG):

```bash
sudo apt-get update && sudo apt-get install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt-get install -y postgresql-16
```

## 5. Network restriction (VCN NSG + host firewall)

Only the staging app VM may reach 5432. NSG example (attach to the DB VM's
VNIC):

```bash
OCI_CLI_AUTH=security_token oci network nsg create \
  --compartment-id CHANGE_ME_COMPARTMENT_OCID --vcn-id CHANGE_ME_VCN_OCID \
  --display-name thesis-staging-db-nsg

OCI_CLI_AUTH=security_token oci network nsg rules add \
  --nsg-id CHANGE_ME_NSG_OCID --security-rules '[
    {"direction":"INGRESS","protocol":"6","isStateless":false,
     "source":"CHANGE_ME_APP_VM_PRIVATE_IP/32","sourceType":"CIDR_BLOCK",
     "tcpOptions":{"destinationPortRange":{"min":5432,"max":5432}},
     "description":"thesis-staging app VM to PostgreSQL only"}
  ]'
```

Optionally add a second rule for TCP 22 from `CHANGE_ME_OWNER_IP/32` only.
Belt-and-braces on the host itself:

```bash
sudo ufw default deny incoming
sudo ufw allow from CHANGE_ME_APP_VM_PRIVATE_IP/32 to any port 5432 proto tcp
sudo ufw allow from CHANGE_ME_OWNER_IP/32 to any port 22 proto tcp   # if SSH needed
sudo ufw enable
```

Remember OCI subnets also have a security list — ensure it doesn't
independently open 5432 wider than the NSG.

## 6. TLS configuration

Self-signed server certificate (staging-grade; the DB host has no public DNS):

```bash
sudo openssl req -new -x509 -days 397 -nodes \
  -subj "/CN=thesis-staging-db" \
  -keyout /etc/postgresql/16/main/server.key \
  -out /etc/postgresql/16/main/server.crt
sudo chown postgres:postgres /etc/postgresql/16/main/server.{key,crt}
sudo chmod 600 /etc/postgresql/16/main/server.key
```

Honesty note: `ssl=require` (client side) **encrypts but does not
authenticate the server** — no MITM protection. Inside a private VCN with an
NSG-pinned source that is an accepted staging trade-off. `verify-full` with a
distributed CA cert is production hardening, out of staging scope.

`/etc/postgresql/16/main/postgresql.conf` — settings that matter here:

```conf
listen_addresses = 'CHANGE_ME_DB_VM_PRIVATE_IP'
port = 5432
max_connections = 220                      # sizing math in §9
superuser_reserved_connections = 3
password_encryption = scram-sha-256
ssl = on
ssl_cert_file = '/etc/postgresql/16/main/server.crt'
ssl_key_file  = '/etc/postgresql/16/main/server.key'
ssl_min_protocol_version = 'TLSv1.2'
shared_buffers = 1536MB                    # ~25% of 6 GB
effective_cache_size = 4GB
work_mem = 4MB                             # keep low: 220 potential backends
maintenance_work_mem = 256MB
idle_in_transaction_session_timeout = 300000   # 5 min
log_checkpoints = on
log_lock_waits = on
log_statement = 'ddl'                      # NEVER 'all' — INSERT literals contain
log_min_duration_statement = -1            # thesis prose (data-map rule 1)
shared_preload_libraries = 'pg_stat_statements'   # optional ops extension, §3
```

`/etc/postgresql/16/main/pg_hba.conf` — default-deny; TLS mandatory; role- and
host-scoped:

```conf
# TYPE    DATABASE          USER                    ADDRESS                              METHOD
local     all               postgres                                                     peer
# App role from the staging app VM only, TLS only. "all" databases so the
# restore drill can hit postgres/thesis_staging_drill (see §11).
hostssl   all               thesis_staging          CHANGE_ME_APP_VM_PRIVATE_IP/32       scram-sha-256
# Backup role, also from the app VM (backups run there per STAGING_PROVISIONING §6).
hostssl   thesis_staging    thesis_staging_backup   CHANGE_ME_APP_VM_PRIVATE_IP/32       scram-sha-256
# No other host lines. Anything unmatched is rejected.
```

`sudo systemctl restart postgresql@16-main` after both files change.

## 7. Initial creation SQL (staging-only credentials)

Run as `postgres` on the DB VM (`sudo -u postgres psql`). Generate passwords
with `openssl rand -base64 24`; set them with `\password <role>` (client-side
hashing — the plaintext never reaches server logs or `psql` history).

```sql
CREATE ROLE thesis_staging LOGIN
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  CONNECTION LIMIT 200;
\password thesis_staging

CREATE DATABASE thesis_staging OWNER thesis_staging;
REVOKE ALL ON DATABASE thesis_staging FROM PUBLIC;

\connect thesis_staging
-- PG15+ already denies CREATE on public to PUBLIC; make it explicit and give
-- the schema to the app role (alembic creates all objects here).
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO thesis_staging;

-- Optional read-only backup role. pg_read_all_data (PG14+) covers current
-- AND future tables, so pg_dump keeps working after every migration.
CREATE ROLE thesis_staging_backup LOGIN
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  CONNECTION LIMIT 3;
\password thesis_staging_backup
GRANT CONNECT ON DATABASE thesis_staging TO thesis_staging_backup;
GRANT pg_read_all_data TO thesis_staging_backup;
```

These credentials exist **only** for staging. They never appear in chat,
commits, logs, or CI output; they live in the host `.env`
(`${STAGING_ENV_PATH}`, chmod 600), the backup env file (§10), and the
owner's password manager. There is deliberately no production counterpart yet.

## 8. Connection string + what the verifier actually enforces

URL shape (the exact form `.env.staging.example` templates):

```
DATABASE_URL=postgresql+asyncpg://thesis_staging:CHANGE_ME@CHANGE_ME_DB_VM_PRIVATE_IP:5432/thesis_staging?ssl=require
```

SQLAlchemy's asyncpg dialect passes `ssl=require` through to asyncpg, which
negotiates TLS without server verification (§6 note). For libpq tools
(`psql`, `pg_dump`, `pg_restore`) the equivalent is `sslmode=require` or
`export PGSSLMODE=require` — asyncpg honors `PGSSLMODE` too, which matters
for the restore drill (§11).

`scripts/verify_phase5_environment.py --target staging` acceptance rules, as
implemented (read 2026-07-12):

1. `DATABASE_URL` must be non-empty and must not contain `replace_me`
   (case-insensitive). **Gotcha: `CHANGE_ME` passes this check** — the
   verifier will not catch an unreplaced `CHANGE_ME` placeholder. Replacing
   them is on you.
2. Hostname parsed from the URL must **not** be `localhost`, `127.0.0.1`,
   `postgres`, or `db` — any of those is a hard **error** ("Release database
   must be isolated from the application host").
3. If neither `ssl=` nor `sslmode=` appears anywhere in the URL it emits a
   **warning only**, not an error. This spec still mandates `?ssl=require`;
   don't lean on the verifier's leniency.
4. `ENV=staging`, `STORAGE_BACKEND=r2`, `DEBUG` falsy, plus the unrelated
   required-secret presence checks.

## 9. Connection-pool math → `max_connections`

`app/db/session.py` (actual values, read 2026-07-12): one module-level async
engine per process with `pool_size=10`, `max_overflow=20`,
`pool_pre_ping=True`. **These are hardcoded — no environment override
exists** — so the database must be sized to the app, not vice versa.

`deploy/compose.phase5.yml` runs six app processes: `web-a`, `web-b`,
`worker-general`, `worker-ai`, `worker-pdf`, `maintenance`.

| Consumer | Worst-case connections |
|---|---:|
| 6 app processes × (10 pool + 20 overflow) | 180 |
| One-off `alembic upgrade head` container (§10) | 2 |
| `pg_dump` backup (§10) | 1 |
| Restore drill engines + client tools (§11) | 4 |
| Operator `psql` / monitoring | 2 |
| **Worst-case total (app role + operator)** | **189** |
| `superuser_reserved_connections` | 3 |

Settings derived: `max_connections = 220` (headroom above 189+3), app role
`CONNECTION LIMIT 200` (protects superuser/backup slots even if the app
saturates), backup role `CONNECTION LIMIT 3`. Steady-state staging usage is
actually ~10–60 connections (pools open lazily); the 180 figure is the
correctness bound, not a memory-planning number. On 6 GB with
`work_mem=4MB` this is safe because real concurrency stays tiny; if
`pg_stat_activity` ever shows sustained triple digits on staging, investigate
the app, don't raise the limit. Managed-provider consequence: any provider
whose ceiling is below ~190 direct connections (Neon free at 112, Supabase
micro at ~60) can be exhausted by this app **as configured**, since the pool
settings cannot be tuned down via env.

## 10. Migrations, backups, backup verification

### 10.1 Where `alembic upgrade head` actually runs

Honest reading of `.github/workflows/phase5-release.yml`: the workflow's
"Migration expansion/rollback validation" step (`alembic upgrade head` →
`downgrade 0016` → `upgrade head`) runs against
`RELEASE_VALIDATION_DATABASE_URL` — a **throwaway CI database, not staging**.
The `deploy-staging` job (pull → `verify_phase5_environment` → `up -d`)
**contains no alembic step against the staging database**, and the app does
not migrate at startup. Applying the schema to staging is therefore an
**operator step on the staging app VM**, run before the containers first
start (and again before `up` whenever a new release adds migrations —
back up first, per `docs/runbooks/backup-restore.md` "Before a risky
migration"):

```bash
export ROBOFOX_IMAGE=ghcr.io/febufenn-cyber/thesis-studio-backend:b2c9c624cd6b6faffe4f9585ac7f4580631abd82
export CLAMAV_IMAGE='clamav/clamav:1.4.5@sha256:86c2a50372da8522186cc8f68e23ebebe9782c7eac21439a6fece9e1a867d038'
export ROBOFOX_ENV_FILE=CHANGE_ME_STAGING_ENV_PATH
export BACKUP_EVIDENCE_HOST_PATH=/dev/null
cd CHANGE_ME_STAGING_DEPLOY_PATH
docker compose -f deploy/compose.phase5.yml pull web-a
# --no-deps: skip the clamav service_healthy wait; alembic doesn't need it.
docker compose -f deploy/compose.phase5.yml run --rm --no-deps web-a alembic upgrade head
docker compose -f deploy/compose.phase5.yml run --rm --no-deps web-a alembic current   # expect: 0018 (head)
```

The image carries `alembic==1.14.0`, `alembic.ini`
(`script_location = migrations`), and the migrations; the URL comes from
`DATABASE_URL` in the env file via `migrations/env.py` → `app.core.config`.
Sequence in the release flow: **provision DB (§4–§7) → write `.env` → run the
one-off `alembic upgrade head` above → then dispatch
`phase5-release.yml -f environment=staging`.**

### 10.2 Automated backups (app VM → R2 `backups/`, 30-day lifecycle)

Runs on the staging app VM (it already has the network path and R2-scoped
credentials; the DB VM holds no R2 token). Install clients once:
`sudo apt-get install -y postgresql-client-16 awscli`.

`/etc/thesis-staging/backup.env` (chmod 600, root-owned):

```bash
PGPASSWORD=CHANGE_ME_THESIS_STAGING_BACKUP_PASSWORD
PGSSLMODE=require
AWS_ACCESS_KEY_ID=CHANGE_ME_STAGING_ONLY_R2_TOKEN
AWS_SECRET_ACCESS_KEY=CHANGE_ME_STAGING_ONLY_R2_TOKEN
R2_ENDPOINT=https://CHANGE_ME_R2_ACCOUNT_ID.r2.cloudflarestorage.com
DB_HOST=CHANGE_ME_DB_VM_PRIVATE_IP
```

`/usr/local/bin/thesis-staging-backup.sh` (chmod 755):

```bash
#!/usr/bin/env bash
set -euo pipefail
source /etc/thesis-staging/backup.env
export PGPASSWORD PGSSLMODE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DUMP=/tmp/thesis-staging-${STAMP}.dump
pg_dump -h "$DB_HOST" -p 5432 -U thesis_staging_backup -d thesis_staging -Fc -f "$DUMP"
sha256sum "$DUMP" > "${DUMP}.sha256"
aws s3 cp "$DUMP"        "s3://thesis-staging/backups/" --endpoint-url "$R2_ENDPOINT"
aws s3 cp "${DUMP}.sha256" "s3://thesis-staging/backups/" --endpoint-url "$R2_ENDPOINT"
date -u +%Y-%m-%dT%H:%M:%SZ > /var/lib/thesis-staging/last-backup-ok   # monitoring stamp (§12)
rm -f "$DUMP" "${DUMP}.sha256"
```

Systemd timer (nightly 20:30 UTC = 02:00 IST):

```ini
# /etc/systemd/system/thesis-staging-backup.service
[Unit]
Description=Nightly staging pg_dump to R2
[Service]
Type=oneshot
ExecStart=/usr/local/bin/thesis-staging-backup.sh

# /etc/systemd/system/thesis-staging-backup.timer
[Timer]
OnCalendar=*-*-* 20:30:00 UTC
Persistent=true
[Install]
WantedBy=timers.target
```

`sudo mkdir -p /var/lib/thesis-staging && sudo systemctl enable --now thesis-staging-backup.timer`.
R2 lifecycle already expires `backups/` at 30 days
(`deploy/r2-lifecycle-staging.json`, `expire-staging-backups`).

### 10.3 PITR — honest status

Nightly `pg_dump` gives a worst-case **RPO of ~24 hours**, which does **not**
meet the internal 15-minute RPO target. Accepted for staging and documented
here as a known gap. If staging must *demonstrate* the 15-minute RPO before
production sign-off, add pgBackRest with WAL archiving to R2
(`archive_mode=on`, `archive_command` via pgBackRest, `repo1-type=s3` pointed
at the R2 endpoint, `archive-push` latency well under 15 min) — a real but
non-trivial extra system to operate. Neon/managed options provide PITR
natively (§2). Do not claim the 15-minute RPO anywhere until a drill proves it.

### 10.4 Backup verification (restore into an isolated DB — never the live one)

Monthly, or before any risky migration. On the app VM:

```bash
source /etc/thesis-staging/backup.env
export PGPASSWORD PGSSLMODE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
aws s3 cp "s3://thesis-staging/backups/thesis-staging-CHANGE_ME_STAMP.dump" /tmp/verify.dump \
  --endpoint-url "$R2_ENDPOINT"
aws s3 cp "s3://thesis-staging/backups/thesis-staging-CHANGE_ME_STAMP.dump.sha256" /tmp/ \
  --endpoint-url "$R2_ENDPOINT"
( cd /tmp && sha256sum -c thesis-staging-CHANGE_ME_STAMP.dump.sha256 )

# Isolated target (as the app role; needs the temporary CREATEDB grant, §11):
export PGPASSWORD=CHANGE_ME_THESIS_STAGING_PASSWORD
createdb -h "$DB_HOST" -U thesis_staging thesis_staging_verify
pg_restore --no-owner --no-privileges -h "$DB_HOST" -U thesis_staging \
  -d thesis_staging_verify /tmp/verify.dump
psql -h "$DB_HOST" -U thesis_staging -d thesis_staging_verify \
  -c "SELECT version_num FROM alembic_version;" \
  -c "SELECT count(*) FROM projects;" \
  -c "SELECT count(*) FROM users;"
dropdb -h "$DB_HOST" -U thesis_staging thesis_staging_verify
rm -f /tmp/verify.dump /tmp/thesis-staging-CHANGE_ME_STAMP.dump.sha256
```

## 11. Full restore drill (`scripts/run_restore_drill.py`) on staging

The drill seeds a synthetic project, dumps, restores into an isolated DB, and
emits pass/fail JSON evidence. Staging invocation (matches
`STAGING_PROVISIONING.md` §6), run **from the staging app VM** — it is the
only host that can reach 5432:

```bash
export DRILL_PG_PASSWORD=CHANGE_ME_THESIS_STAGING_PASSWORD   # defaults to 'thesis' if unset — always set it
export PGSSLMODE=require                                     # honored by pg_dump/psql AND asyncpg
python scripts/run_restore_drill.py \
  --source-db thesis_staging --restore-db thesis_staging_drill \
  --pg-host CHANGE_ME_DB_VM_PRIVATE_IP --pg-port 5432 --pg-user thesis_staging \
  --evidence-out docs/release/evidence/RESTORE_DRILL_STAGING_CHANGE_ME_DATE.json
```

Prerequisites and honest gotchas, verified against the script:

1. **Where it runs:** it imports the app's ORM, so it needs a repo checkout at
   the target release SHA plus a Python 3.11 venv with
   `pip install -r requirements.txt` on the app VM. It cannot run inside the
   app container (no pg client binaries in the image) — install
   `postgresql-client-16` on the host; the script falls back from
   `docker exec` (container `thesis-postgres`, which doesn't exist on
   staging) to PATH-visible host client binaries automatically.
2. **CREATEDB:** the drill runs `dropdb`/`createdb thesis_staging_drill` as
   `--pg-user`. Our role is `NOCREATEDB` (§7), so grant it for the drill
   window only: `ALTER ROLE thesis_staging CREATEDB;` before, and
   `ALTER ROLE thesis_staging NOCREATEDB;` immediately after.
3. **Name guard:** it refuses any database not matching `^thesis_[a-z0-9_]*$`
   and refuses `--restore-db` equal to `--source-db`.
4. **Seeds stay:** the synthetic drill rows are committed to the SOURCE
   database and left there (`seed_left_in_source: true` in the evidence) —
   expected on staging; institution short-name/slug are `DR<runid>` /
   `drill-<runid>`.
5. Evidence `environment` is hardcoded `local-development-macos` — cosmetic;
   note the real environment in the evidence PR description.
6. The drill also sets `os.environ.setdefault("DATABASE_URL", …localhost…)` —
   that default is only a settings bootstrap for imports; the real
   connections use the `--pg-*` flags.
7. Pass criterion: exit 0 and `"status": "passed"` in the JSON. Then write the
   evidence path into `BACKUP_EVIDENCE_PATH` per `STAGING_PROVISIONING.md` §6.

## 12. Monitoring (minimal, solo-operator honest)

App side already exists: `/readyz` (checked by compose healthchecks, nginx
upstream failover, and `scripts/phase5_smoke.py`) fails if the DB is
unreachable. Add a DB-side timer on the DB VM
(`/usr/local/bin/thesis-staging-db-check.sh`, systemd timer every 5 min):

```bash
#!/usr/bin/env bash
set -euo pipefail
FAIL=0
pg_isready -h CHANGE_ME_DB_VM_PRIVATE_IP -p 5432 -q || FAIL=1
CONN=$(sudo -u postgres psql -Atc "SELECT count(*) FROM pg_stat_activity WHERE usename='thesis_staging';")
[ "$CONN" -lt 190 ] || FAIL=1                      # approaching CONNECTION LIMIT 200
DISK=$(df --output=pcent /var/lib/postgresql | tail -1 | tr -dc 0-9)
[ "$DISK" -lt 85 ] || FAIL=1
# Backup freshness (stamp written by §10.2 on the app VM; sync or check there instead)
if [ "$FAIL" -eq 0 ]; then
  curl -fsS -m 10 CHANGE_ME_HEALTHCHECK_PING_URL >/dev/null || true   # e.g. healthchecks.io
fi
exit "$FAIL"
```

A dead-man's-switch ping URL (healthchecks.io free tier or similar) turns
"script stopped running" into an email without running any alerting stack.
Watch three numbers weekly: `pg_stat_activity` count, disk %, and the age of
the newest object under `s3://thesis-staging/backups/`. `pg_stat_statements`
(§3) gives query-shape visibility without logging literals.

## 13. Deltas if you choose Neon paid instead

Skip §4–§7 and §10.2–10.3 (managed backups/PITR). Create role/database
through Neon's console/CLI with the same names; keep `?ssl=require` (Neon
enforces TLS anyway). Use the **direct (unpooled)** connection string at
≥0.5 CU so 180 worst-case connections fit; do not use the PgBouncer pooled
endpoint with asyncpg unless it is session mode. IP allowlist (paid feature)
→ pin to the app VM's egress IP. The restore drill needs `CREATEDB` on the
role (Neon roles can create databases by default) and `PGSSLMODE=require`.
Latency caveat from §2 applies to every staging perf number you record.

## 14. Credential rotation (staging DB)

Where the credential lives — exact inventory: the host `.env` at
`${STAGING_ENV_PATH}` (`DATABASE_URL`), the backup env
`/etc/thesis-staging/backup.env` (backup role), and the owner's password
manager. **No GitHub staging secret contains the staging `DATABASE_URL`**
(`scripts/check_staging_secrets.py` list: `STAGING_HOST/USER/SSH_KEY/ENV_PATH/DEPLOY_PATH/BASE_URL`,
`CLAMAV_IMAGE`; the repo-level `RELEASE_VALIDATION_DATABASE_URL` is a
throwaway CI database, **not** staging — rotating staging never touches it).
If a future workflow ever consumes the staging DB URL as a GH secret, add it
to this inventory first.

### Variant A — routine password rotation (same role)

1. Generate: `openssl rand -base64 24` (into the password manager, nowhere else).
2. On the DB VM: `sudo -u postgres psql -c '\password thesis_staging'` —
   paste twice. Client-side hashed; nothing in server logs or shell history.
   Existing pooled connections stay alive (passwords are checked only at
   connect time), so nothing breaks yet.
3. Update `DATABASE_URL` in `${STAGING_ENV_PATH}` on the app VM with an
   editor (not `sed` — argv leaks into shell history/process list). Confirm
   `chmod 600`.
4. Rolling restart so every process reconnects with the new secret:

   ```bash
   cd CHANGE_ME_STAGING_DEPLOY_PATH
   docker compose -f deploy/compose.phase5.yml up -d --force-recreate web-a
   curl -fsS http://127.0.0.1:8101/readyz          # wait for 200
   docker compose -f deploy/compose.phase5.yml up -d --force-recreate web-b
   curl -fsS http://127.0.0.1:8102/readyz
   docker compose -f deploy/compose.phase5.yml up -d --force-recreate \
     worker-general worker-ai worker-pdf maintenance
   ```

5. Verify: `https://thesis-staging.robofox.online/readyz` returns 200, and on
   the DB VM
   `sudo -u postgres psql -c "SELECT count(*) FROM pg_stat_activity WHERE usename='thesis_staging';"`
   shows fresh connections. The old password is already invalid for new
   connections — rotation complete once all six processes are recreated.
6. Rotate `thesis_staging_backup` the same way (steps 1–3 against
   `/etc/thesis-staging/backup.env`), then run one manual
   `sudo systemctl start thesis-staging-backup.service` to prove it.

### Variant B — suspected compromise (new role, then revoke old)

1. Create the replacement and give it the old role's rights and future object
   ownership behavior:

   ```sql
   CREATE ROLE thesis_staging_v2 LOGIN
     NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 200;
   \password thesis_staging_v2
   GRANT thesis_staging TO thesis_staging_v2;          -- inherits all privileges
   ALTER ROLE thesis_staging_v2 IN DATABASE thesis_staging SET role = 'thesis_staging';
   -- ^ objects created by future alembic runs stay owned by thesis_staging
   ```

2. Add an explicit `pg_hba.conf` line for `thesis_staging_v2` (same
   host/TLS/method as §6) and `sudo systemctl reload postgresql@16-main`.
3. Update `${STAGING_ENV_PATH}` `DATABASE_URL` to the new role, rolling
   restart exactly as Variant A step 4, verify as step 5.
4. Revoke the old credential — order matters, do this only after `/readyz`
   is green on the new role:

   ```sql
   ALTER ROLE thesis_staging NOLOGIN;
   SELECT pg_terminate_backend(pid) FROM pg_stat_activity
    WHERE usename = 'thesis_staging';
   ```

   Keep the `thesis_staging` role itself (it owns the database, the schema,
   and every object; `NOLOGIN` neutralizes it). If you later want the new
   role to be the permanent identity, run `REASSIGN OWNED BY thesis_staging
   TO thesis_staging_v2;` in `thesis_staging` **and** drop the
   `SET role` default from step 1 — do not drop the old role before
   reassignment.
5. Remove the old role's `pg_hba.conf` line, reload, update the backup role
   likewise if it was exposed, and record the rotation (date, reason, scope —
   no secret values) in the staging evidence notes.

## 15. Out of scope

Production databases, production secrets, and the shared Oracle VM
(`68.233.116.11`) are untouched. No file in `app/`, `deploy/`, or
`migrations/` changes for any of this — the app's pool settings are taken as
fixed inputs. AI and billing behavior are irrelevant to this spec beyond the
fixed `AI_GLOBAL_ENABLED=false` / `BILLING_PROVIDER=manual` decisions already
encoded in `.env.staging.example`.
