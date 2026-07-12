# Staging Provisioning Runbook

Date: 2026-07-12 · Target release: main `b2c9c624cd6b6faffe4f9585ac7f4580631abd82`
Decisions encoded (owner, 2026-07-12): AI deterministic degraded mode
(`AI_GLOBAL_ENABLED=false`), billing manual mode, isolated staging host,
external TLS PostgreSQL, dedicated staging R2 bucket, protected environments,
no production changes, no credentials in chat/commits/logs.

## Pre-deploy gate status (checked 2026-07-12)

| Precondition | Status |
|---|---|
| Post-merge Main Release Candidate workflow | **passed** on `b2c9c62` |
| Durable attestation identifies merge SHA | **yes** — `release-candidates/b2c9c624….json`: 174/0/0/0, image passed, migration passed, `deployment_triggered:false` |
| Required staging secrets exist | **no** — run `python scripts/check_staging_secrets.py` (names-only check) |
| Environment verification | pending host + `.env` (`verify_phase5_environment.py --target staging`) |
| Immutable image digest recorded | pending — GHCR push happens in the release workflow's verify job; record the digest it prints into the staging acceptance evidence |

## 1. Host specification (blocker: owner creates)

**Architecture constraint: the release image is `linux/amd64`** (built on
`ubuntu-latest` in `phase5-release.yml`). OCI **A1 (ARM) free tier cannot run
it**. Options:
- **Recommended:** `VM.Standard.E4.Flex` — 2 OCPU / 16 GB RAM / 100 GB boot,
  Ubuntu 22.04 x86_64 (ClamAV alone holds ~1.5–3.5 GB of signatures in RAM;
  LibreOffice worker + 2 web + 3 workers + nginx need the rest).
- Alternative (needs a future, separately-approved workflow change): add
  `docker buildx` multi-arch to `phase5-release.yml`, then A1.Flex 4 OCPU/24 GB
  free tier becomes usable.

```bash
OCI_CLI_AUTH=security_token oci compute instance launch \
  --availability-domain <AD> --compartment-id <compartment-ocid> \
  --shape VM.Standard.E4.Flex --shape-config '{"ocpus":2,"memoryInGBs":16}' \
  --image-id <ubuntu-2204-x86_64-image-ocid> \
  --display-name thesis-staging --subnet-id <subnet-ocid> \
  --assign-public-ip true --ssh-authorized-keys-file <staging-only-pubkey>
```

Host prep (after SSH in): install `docker.io docker-compose-plugin nginx cloudflared`,
create `${STAGING_DEPLOY_PATH}` containing `deploy/compose.phase5.yml`, install
`deploy/nginx-staging.conf`, place the real `.env` from `.env.staging.example`
at `${STAGING_ENV_PATH}` (chmod 600), and `docker login ghcr.io` with a
read-only package token.

## 2. Firewall / ingress

- OCI security list / NSG: **no inbound rules** except (optionally) TCP 22
  restricted to the owner's current IP. All HTTP ingress rides the Cloudflare
  Tunnel's outbound connections.
- Tunnel: `cloudflared tunnel create thesis-staging`, then
  `deploy/cloudflared-staging.example.yml` → `/etc/cloudflared/config.yml`,
  `cloudflared tunnel route dns thesis-staging thesis-staging.robofox.online`,
  run as systemd service.
- nginx (`deploy/nginx-staging.conf`) listens only on `127.0.0.1:8100` and
  balances web-a/web-b with failure-aware upstreams.
- Optional: Cloudflare Access policy in front of the staging hostname
  (staging is not for the public).

## 3. Isolated PostgreSQL (blocker: owner creates)

Requirements: PostgreSQL 16, **not on the staging app host**, TLS enforced,
reachable only from the staging VM (VCN security rule or provider allowlist).
Database `thesis_staging`, role `thesis_staging` (no SUPERUSER), plus a
separate read-only role for backups if the provider supports it. URL shape the
verifier accepts:
`postgresql+asyncpg://thesis_staging:<pw>@<db-host>:5432/thesis_staging?ssl=require`.
Migrations are applied by the release workflow (`alembic upgrade head`).

## 4. R2 bucket + least-privilege credential (blocker: owner creates)

1. Create bucket `thesis-staging` (Cloudflare dashboard → R2).
2. API token: **Object Read & Write, scoped to bucket `thesis-staging` only**
   — never account-wide, never the production token (which doesn't exist yet;
   keep it that way until production provisioning).
3. Apply lifecycle rules (previews 7d, temp 1d, backups 30d, abort incomplete
   multipart 1d; durable prefixes untouched):

```bash
aws s3api put-bucket-lifecycle-configuration --bucket thesis-staging \
  --endpoint-url https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com \
  --lifecycle-configuration file://deploy/r2-lifecycle-staging.json
aws s3api get-bucket-lifecycle-configuration --bucket thesis-staging \
  --endpoint-url https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com
```

## 5. DNS

`thesis-staging.robofox.online` CNAME → `<tunnel-id>.cfargotunnel.com`
(proxied). Created automatically by `cloudflared tunnel route dns`.

## 6. Backup destination + restore drill (staging)

- Destination: `backups/` prefix in the staging bucket (30-day lifecycle).
- Backup (from the staging VM; requires host `postgresql-client-16` + `aws` CLI):

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
pg_dump "$DATABASE_URL_PSQL_FORM" -Fc -f /tmp/thesis-staging-$STAMP.dump
sha256sum /tmp/thesis-staging-$STAMP.dump > /tmp/thesis-staging-$STAMP.dump.sha256
aws s3 cp /tmp/thesis-staging-$STAMP.dump s3://thesis-staging/backups/ \
  --endpoint-url https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com
```

- Restore drill against staging data (isolated DB on the DB host, never over
  the live database):

```bash
python scripts/run_restore_drill.py \
  --source-db thesis_staging --restore-db thesis_staging_drill \
  --pg-host <db-host> --pg-port 5432 --pg-user thesis_staging \
  --evidence-out docs/release/evidence/RESTORE_DRILL_STAGING_<date>.json
```

Write the backup-evidence JSON path into the staging host env
(`BACKUP_EVIDENCE_PATH`) once the first drill passes — production deploys
later require it.

## 7. Secrets (owner runs; values via stdin, never argv/chat/logs)

```bash
REPO=febufenn-cyber/thesis-studio-backend
gh secret set STAGING_HOST        --env staging --repo $REPO   # paste value, Ctrl-D
gh secret set STAGING_USER        --env staging --repo $REPO
gh secret set STAGING_SSH_KEY     --env staging --repo $REPO < ~/.ssh/thesis_staging_deploy
gh secret set STAGING_ENV_PATH    --env staging --repo $REPO
gh secret set STAGING_DEPLOY_PATH --env staging --repo $REPO
gh secret set STAGING_BASE_URL    --env staging --repo $REPO   # https://thesis-staging.robofox.online
printf 'clamav/clamav:1.4.5@sha256:86c2a50372da8522186cc8f68e23ebebe9782c7eac21439a6fece9e1a867d038' \
  | gh secret set CLAMAV_IMAGE --env staging --repo $REPO
gh secret set RELEASE_VALIDATION_DATABASE_URL --repo $REPO     # throwaway CI Postgres URL
python scripts/check_staging_secrets.py   # presence check, names only
```

## 8. Deploy + post-deploy (run only after every gate above is green)

```bash
gh workflow run phase5-release.yml \
  -f environment=staging \
  -f expected_sha=b2c9c624cd6b6faffe4f9585ac7f4580631abd82
gh run watch   # verify job re-checks attestation, pushes ghcr image (record its digest)

# Smoke (also run automatically by the workflow):
python scripts/phase5_smoke.py \
  --base-url https://thesis-staging.robofox.online \
  --expected-release b2c9c624cd6b6faffe4f9585ac7f4580631abd82

# UAT driver + human checklists:
python scripts/run_uat_flows.py --base-url https://thesis-staging.robofox.online \
  --out docs/release/evidence/UAT_STAGING_RAW.json
# docs/release/evidence/UAT_CHECKLISTS.md → human items

# Restore drill: section 6. Load tests: scripts/run_local_perf.py notes +
# docs/release/evidence/PERF_LOCAL.md thresholds; 25/50/100-user runs become
# possible once this host exists.
```

## Explicitly out of scope for staging

Production secrets, DNS, database, storage, services: **untouched**. The
shared Oracle VM (68.233.116.11): not used for staging. Claude CLI/OAuth
session: not a staging dependency (AI is disabled). Real charging: none
(`BILLING_PROVIDER=manual`).
