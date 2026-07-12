# Staging Deployment Blockers

Status date: 2026-07-12 · Assessed at commit `7397fdc` (RC `0941ebda78fb7b1b3e522e95b609a7f35e15ba73`)
Assessment method: GitHub REST API (environments, actions secrets), DNS queries, local repository inspection, prior verified host state (2026-07-11).

**Staging deployment is BLOCKED.** The official release workflow
(`.github/workflows/phase5-release.yml`) is dispatch-ready and the release
candidate is attested, but none of the infrastructure or secrets it consumes
exist. Nothing below is invented; every blocker was verified empty/absent.

## Verified-absent inventory

| # | Missing item | Verified how | Owner |
|---|---|---|---|
| 1 | GitHub environment `staging` (protected) | `gh api repos/febufenn-cyber/thesis-studio-backend/environments` → `{"total_count":0}` | Febin |
| 2 | GitHub environment `production` (protected, required reviewers) | same call | Febin |
| 3 | All 16 Actions secrets used by `phase5-release.yml` | `gh api .../actions/secrets` → `{"total_count":0}` | Febin |
| 4 | Isolated staging application host | No host exists. The only VM (Oracle `68.233.116.11`) runs LeadFinder + marketing site + v1 thesis-api with Postgres on-host — violates `docs/phase5/production-topology.md` boundaries 1 and 5, so it may not serve as staging | Febin |
| 5 | Isolated staging PostgreSQL (TLS, off the app host) | No managed/isolated instance exists | Febin |
| 6 | Staging R2 bucket + least-privilege token | Repo/VM `.env`s carry placeholders; no staging bucket created | Febin |
| 7 | ClamAV (pinned image, internal-only) | Not deployed anywhere; `CLAMAV_IMAGE` secret unset | Febin |
| 8 | Governed AI provider credential (commercial or institution-supplied) | No `AI_PROVIDER_*` endpoint/secret configured; the Max-subscription Claude CLI on the v1 VM is the **pilot** path which `PHASE5-COMMERCIAL-OPERATING-CONTRACT.md` forbids as a commercial dependency. Staging must either configure the governed `http_json` provider or deploy with `AI_GLOBAL_ENABLED=false` (deterministic mode — supported and CI-tested) | Febin |
| 9 | Staging DNS record (e.g. `thesis-staging.robofox.online`) | No record exists (Cloudflare zone `robofox.online`) | Febin |
| 10 | Backup-evidence file path on staging host | Host absent (see 4) | Febin |
| 11 | GHCR pull access on the staging host | No host; workflow pushes `ghcr.io/febufenn-cyber/thesis-studio-backend:<sha>` | Febin |

Already satisfied (no action): email provider — Resend key live and verified
sending on 2026-07-11 (domain `robofox.online`: DKIM published at
`resend._domainkey`, SPF `v=spf1 include:amazonses.com ~all` on the `send.`
envelope subdomain, DMARC `p=quarantine` with `rua=`). Billing — `manual`
mode requires no provider. Release candidate — `release-candidates/0941ebd….json`
attested with 173/0/0.

## Exact completion steps

### 1–2. Protected GitHub environments

```bash
gh api -X PUT repos/febufenn-cyber/thesis-studio-backend/environments/staging
# production requires a human reviewer gate:
gh api -X PUT repos/febufenn-cyber/thesis-studio-backend/environments/production \
  -F "reviewers[][type]=User" -F "reviewers[][id]=$(gh api user --jq .id)" \
  -F "deployment_branch_policy[protected_branches]=true" \
  -F "deployment_branch_policy[custom_branch_policies]=false"
```

### 3. Secrets (names from `phase5-release.yml`; set per environment, never echo values)

```bash
# staging environment
for s in STAGING_HOST STAGING_USER STAGING_SSH_KEY STAGING_ENV_PATH \
         STAGING_DEPLOY_PATH STAGING_BASE_URL CLAMAV_IMAGE; do
  gh secret set "$s" --env staging --repo febufenn-cyber/thesis-studio-backend
done
# repo-level
gh secret set RELEASE_VALIDATION_DATABASE_URL --repo febufenn-cyber/thesis-studio-backend
# production environment (later, same pattern):
# PRODUCTION_HOST PRODUCTION_USER PRODUCTION_SSH_KEY PRODUCTION_ENV_PATH
# PRODUCTION_DEPLOY_PATH PRODUCTION_BASE_URL PRODUCTION_CANARY_BASE_URL
# PRODUCTION_BACKUP_EVIDENCE_PATH LATEST_BACKUP_EVIDENCE_B64 CLAMAV_IMAGE
```

`CLAMAV_IMAGE` must be a digest-pinned reference, e.g.
`clamav/clamav:1.4.3@sha256:<digest>` (resolve with `docker buildx imagetools inspect clamav/clamav:1.4.3`).

### 4. Staging host (isolated; do not reuse the shared v1 VM)

Minimum shape per `docs/phase5/production-topology.md`: one VM dedicated to
Thesis Studio staging (2 GB+ RAM for LibreOffice worker headroom), Docker +
compose, ingress via Cloudflare Tunnel only. On OCI (region ap-hyderabad-1,
session auth):

```bash
OCI_CLI_AUTH=security_token oci compute instance launch \
  --availability-domain <AD> --compartment-id <ocid> \
  --shape VM.Standard.A1.Flex --shape-config '{"ocpus":2,"memoryInGBs":8}' \
  --image-id <ubuntu-22.04-aarch64-ocid> --display-name thesis-staging \
  --subnet-id <ocid> --assign-public-ip true
# then: install docker, docker compose plugin, cloudflared; create
# ${STAGING_DEPLOY_PATH} and place deploy/compose.phase5.yml + .env there
```

The staging `.env` must satisfy `scripts/verify_phase5_environment.py --target staging`
(ENV=staging, STORAGE_BACKEND=r2, non-local DB host with `ssl=require`,
MALWARE_SCAN_MODE=clamav, real JWT_SECRET, RELEASE_SHA of the deployed image).

### 5. Isolated PostgreSQL

Options: managed Postgres, or a second dedicated DB host. Not on the app VM.
Connection string form the verifier accepts:
`postgresql+asyncpg://thesis_staging:<pw>@<db-host>:5432/thesis_staging?ssl=require`

### 6. Staging R2 bucket + scoped token

Cloudflare dashboard → R2 → create bucket `thesis-staging` → API token
scoped **Object Read & Write on that bucket only**. Set
`R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET_NAME` in the
staging `.env`. Lifecycle rules per `docs/phase5/data-map.md` (durable
prefixes `originals/ revisions/ sealed/` — no expiry; `previews/ temp/` +
incomplete multipart — expire).

### 7. ClamAV

Already modeled in `deploy/compose.phase5.yml` (service `clamav`, internal
network, no published port). Only needs the pinned `CLAMAV_IMAGE` secret and
host deployment (step 4).

### 9. DNS

```bash
# via Cloudflare dashboard or API: CNAME thesis-staging -> <tunnel-id>.cfargotunnel.com (proxied)
```

### 10. Backup evidence path

After the first staging backup: place its JSON evidence at
`${STAGING_ENV_PATH%/}/backup-evidence.json` and reference it from the env
file; production deploys additionally require `LATEST_BACKUP_EVIDENCE_B64`.

## Dispatch command once unblocked

```bash
gh workflow run phase5-release.yml \
  -f environment=staging \
  -f expected_sha=<exact validated main sha>
# then: python scripts/phase5_smoke.py --base-url https://thesis-staging.robofox.online \
#         --expected-release <sha>
```

## Explicitly not done in this mission

No cloud resources were provisioned, no secrets were created, and no deploy
was attempted — the brief forbids inventing infrastructure, and host/budget
choices (OCI shape, managed-DB provider) are owner decisions.
