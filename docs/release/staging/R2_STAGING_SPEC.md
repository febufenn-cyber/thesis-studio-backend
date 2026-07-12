# R2 Staging Specification — bucket `thesis-staging`

Date: 2026-07-12 · Companion to `docs/release/staging/STAGING_PROVISIONING.md` §4/§6
Fixed decisions encoded here (owner, 2026-07-12): dedicated staging bucket
`thesis-staging`; staging-only least-privilege token(s); `AI_GLOBAL_ENABLED=false`;
`BILLING_PROVIDER=manual`; tunnel-only ingress; **no production changes** (no
production bucket or token exists yet — keep it that way); credentials never
printed anywhere (this doc uses `CHANGE_ME` placeholders only). Staging app host
is ARM64 (OCI `VM.Standard.A1.Flex`, `ap-hyderabad-1`) — multi-arch images exist,
so the only ARM consequence for this spec is installing the **aarch64** AWS CLI
build (section 7).

---

## 1. Prefix reality check — code vs. policy (do this reconciliation first)

The durable/rebuildable policy names one set of prefixes; the code writes a
different set. `docs/security/DATA_INVENTORY.md` (caveats 1 and 2) and
`docs/security/RETENTION_AND_DELETION.md` (gap 4) already flag this mismatch.
Lifecycle rules below target the **real** prefixes, because a lifecycle rule
scoped to a prefix nothing writes protects nothing, and a rule that misses a
real prefix silently leaks storage (or worse — a future "cleanup" rule written
against the aspirational names could hit real durable data if code later reuses
a name differently).

### Prefixes the code actually writes (verified by grep, this branch)

| Real prefix (key shape) | Written by | Content | Durability class |
|---|---|---|---|
| `manuscripts/{user_id}/{project_id}/{revision_id}/original.docx` | `app/api/manuscripts.py:154` | Original uploaded manuscript revisions | **Durable** (this is what the policy calls `originals/`+`revisions/`) |
| `files/{user_id}/{session_id}/{file_id}.docx` | `app/services/compile_service.py:261` | Legacy v1 compiled theses | **Durable** (finished thesis output; not in the policy list at all — policy gap) |
| `exports/{user_id}/{project_id}/{export_id}.{fmt}` | `app/services/export_service.py:217` (also `scripts/run_uat_flows.py:364` for UAT fixtures) | v2 rendered exports (docx/pdf/md/txt) | **Durable in staging.** Topology calls `exports/` "Mixed", but `DATA_INVENTORY.md` caveat 2 records that no `sealed/` prefix exists — sealed submission packages reference export objects by ID (`submission_packages.export_ids`). Sealed custody therefore rides on `exports/` objects, so no expiry rule may ever match `exports/`. |
| `previews/{user_id}/{project_id}/v{version}-{profile_digest}.pdf` | `app/services/preview_service.py:157` | Rendered preview PDFs | **Rebuildable** (app-level retention sweep exists too — 30d default per `RETENTION_AND_DELETION.md`) |
| `backups/…` | No application code. Written only by the operational backup commands in `STAGING_PROVISIONING.md` §6 / section 6 below | `pg_dump` archives + `.sha256` files | **Rebuildable with a 30-day floor** (staging policy) |

Deletion of objects is performed only by the privacy lifecycle executor
(`app/commercial/privacy.py:83,320`) via `storage.delete(key)` — relevant to the
permission matrix in section 5.

### Prefixes the policy names that do NOT exist in code today

`originals/`, `revisions/`, `sealed/`, `sources/`, `temp/`, `failed/` appear in
`docs/phase5/production-topology.md` (durable/rebuildable table) and in the
mission policy, but **nothing writes them**:

- `originals/` + `revisions/` → the code's `manuscripts/…/original.docx` covers both roles today.
- `sealed/` → does not exist; see `exports/` note above (`DATA_INVENTORY.md` caveat 2).
- `sources/` → the citation registry lives in PostgreSQL (`sources`/`quotes` tables, migration 0005), not in R2.
- `temp/`, `failed/` → workers use container tmpfs (`compose.phase5.yml` mounts `/tmp` as tmpfs; preview service uses `tempfile.mkdtemp`), not R2. No failed-artifact prefix is written on error paths — failures are recorded as DB status rows (`status="failed"`), with no object.

**Reconciliation stance for staging:** the six reserved names stay in this spec
as *reserved prefixes* with rules pre-registered where they are rebuildable
(`temp/`, `failed/`), so the day code adopts them the lifecycle already behaves
correctly. The durable reserved names (`originals/`, `revisions/`, `sealed/`,
`sources/`) are simply never matched by any rule — same guarantee as the real
durable prefixes. Renaming code prefixes to match the topology table is a
**code change, out of scope for staging provisioning**; track it against
`DATA_INVENTORY.md` caveat 1.

### Effective staging prefix policy

| Prefix | Status | Lifecycle |
|---|---|---|
| `manuscripts/` | real, durable | **never expired by any rule** |
| `files/` | real (legacy), durable | **never expired by any rule** |
| `exports/` | real, durable-in-staging (sealed custody) | **never expired by any rule** |
| `originals/`, `revisions/`, `sealed/`, `sources/` | reserved, durable | **never expired by any rule** |
| `previews/` | real, rebuildable | expire 7 days (staging) |
| `temp/` | reserved, rebuildable | expire 1 day |
| `failed/` | reserved, rebuildable | expire 7 days |
| `backups/` | operational, staging retention | expire 30 days |
| incomplete multipart uploads (any prefix) | rebuildable | abort after 1 day |

The bucket-wide multipart-abort rule is safe for durable prefixes: it only
removes *never-completed* multipart uploads (boto3 `upload_file` may multipart
large objects; an abandoned part-set is garbage by definition), never completed
objects.

---

## 2. Review of `deploy/r2-lifecycle-staging.json` + corrected rule set

The current file has four rules: `previews/` 7d, `temp/` 1d, `backups/` 30d,
bucket-wide multipart abort 1d. Review findings against section 1:

1. **Correct:** no rule matches any real or reserved durable prefix
   (`manuscripts/`, `files/`, `exports/`, `originals/`, `revisions/`, `sealed/`,
   `sources/`). Keep it that way.
2. **Correct:** `previews/` 7d targets a real prefix; 1d `temp/` and 30d
   `backups/` match the staging policy.
3. **Gap:** no `failed/` 7d rule. The policy requires one (reserved prefix,
   no-op today, correct behavior the day code writes it).
4. **Honesty note:** the `temp/` rule (like the new `failed/` rule) currently
   matches zero objects — code uses container tmpfs, not R2, for temp files.
   The rules are kept as pre-registered policy, not evidence of cleanup.
5. **Comment drift:** the file's `_comment` lists durable prefixes as
   `originals/, revisions/, sealed/, exports/` — the aspirational names, missing
   the real `manuscripts/` and `files/`. The corrected version fixes the comment
   so a future operator checks the right names.

**Corrected rule set** (shown here for review; after review, replace the
contents of `deploy/r2-lifecycle-staging.json` with this JSON — this doc does
not edit that file):

```json
{
  "_comment": "Staging R2 lifecycle — apply with: aws s3api put-bucket-lifecycle-configuration --bucket thesis-staging --endpoint-url https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com --lifecycle-configuration file://deploy/r2-lifecycle-staging.json. DURABLE prefixes — real: manuscripts/, files/, exports/ (exports carry sealed custody, DATA_INVENTORY caveat 2); reserved: originals/, revisions/, sealed/, sources/ — must NEVER be matched by any expiration rule. temp/ and failed/ are reserved rebuildable prefixes (no code writes them yet; rules are pre-registered policy). Verify against docs/release/staging/R2_STAGING_SPEC.md section 1 before applying.",
  "Rules": [
    {
      "ID": "expire-previews",
      "Filter": { "Prefix": "previews/" },
      "Status": "Enabled",
      "Expiration": { "Days": 7 }
    },
    {
      "ID": "expire-temp",
      "Filter": { "Prefix": "temp/" },
      "Status": "Enabled",
      "Expiration": { "Days": 1 }
    },
    {
      "ID": "expire-failed",
      "Filter": { "Prefix": "failed/" },
      "Status": "Enabled",
      "Expiration": { "Days": 7 }
    },
    {
      "ID": "expire-staging-backups",
      "Filter": { "Prefix": "backups/" },
      "Status": "Enabled",
      "Expiration": { "Days": 30 }
    },
    {
      "ID": "abort-incomplete-multipart",
      "Filter": { "Prefix": "" },
      "Status": "Enabled",
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 1 }
    }
  ]
}
```

R2 evaluates lifecycle rules roughly daily; expiry is not instant at the
boundary. `put-bucket-lifecycle-configuration` **replaces** the whole rule set
each time — always apply from the reviewed file, never patch a single rule ad
hoc.

---

## 3. Bucket creation — `thesis-staging`

### Dashboard (exact steps)

1. `https://dash.cloudflare.com` → select the Robofox account → left nav **R2 Object Storage**.
2. **Create bucket**.
3. Bucket name: `thesis-staging` (exact — `.env.staging.example` pins `R2_BUCKET_NAME=thesis-staging`).
4. Location: **Provide a location hint** → **Asia-Pacific (APAC)** — nearest hint to the `ap-hyderabad-1` app VM. (R2 has location *hints*, not hard region pinning; this is best-effort placement, not a residency guarantee.)
5. Storage class: Standard.
6. **Create bucket**. Do NOT enable any public access / custom domain — all access is via the S3 API with the scoped token; downloads reach users only through app-generated presigned URLs.

### Wrangler equivalent

```bash
# Wrangler authenticates via `wrangler login` (browser OAuth) or
# CLOUDFLARE_API_TOKEN in the environment — never paste tokens into argv.
npx wrangler r2 bucket create thesis-staging --location apac
npx wrangler r2 bucket list        # confirm it exists
```

### Raw API equivalent

```bash
# Requires an account-level API token with R2 admin permission (owner-held,
# NOT the staging app token). Token supplied via env var, not argv history:
# export CLOUDFLARE_API_TOKEN=CHANGE_ME   (enter in a fresh shell, then unset)
curl -sS -X POST \
  "https://api.cloudflare.com/client/v4/accounts/CHANGE_ME_ACCOUNT_ID/r2/buckets" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{"name":"thesis-staging","locationHint":"apac"}'
```

---

## 4. Staging API token — Object R/W, one bucket only

R2 S3-API credentials come from **Account API Tokens** (R2 API tokens are
account-owned tokens that mint an S3 `Access Key ID` / `Secret Access Key`
pair).

### Dashboard (exact path; menu labels may drift slightly with dashboard updates)

1. `https://dash.cloudflare.com` → account → **R2 Object Storage** → **API** → **Manage API tokens** (this lands on the **Account API Tokens** page).
2. **Create Account API token**.
3. Token name: `thesis-staging-app` (name the purpose; you will create more than one — see section 5).
4. Permissions: **Object Read & Write** (NOT Admin Read & Write — the app must not be able to create/delete buckets or edit lifecycle).
5. Bucket scope: **Apply to specific buckets only** → select `thesis-staging` only.
6. TTL: optional; for staging set e.g. 90 days so a forgotten token dies on its own. Client IP filtering: optional — the staging VM's egress IP if it is stable.
7. **Create**. The dashboard shows the Token value, the S3 **Access Key ID**, the S3 **Secret Access Key**, and the endpoint `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com` **once**. Copy the Access Key ID and Secret directly into `${STAGING_ENV_PATH}` on the staging host (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, chmod 600) — never into chat, commits, logs, or shell history.

### API/wrangler equivalents — honest note

Wrangler has no command to create R2 API tokens. Account API tokens *can* be
created via `POST /accounts/{account_id}/tokens` with a policy referencing the
R2 bucket-item read/write permission groups scoped to the one bucket, but the
payload requires permission-group IDs looked up from
`GET /accounts/{account_id}/tokens/permission_groups`, and the S3 secret is
derived from the returned token value. For a solo operator this is more
error-prone than the dashboard flow; **use the dashboard** and treat the API
path as automation-later.

---

## 5. Least-privilege permission matrix

Intended access per principal:

| Principal | manuscripts/ (≙ originals/+revisions/) | files/ (legacy) | exports/ | previews/ | temp/, failed/ (reserved) | sealed/ (reserved) | backups/ | Delete rights |
|---|---|---|---|---|---|---|---|---|
| web/API (web-a, web-b) | read + write | read + write | read + write | read + write | read + write | read only (no delete ever) | none | object delete only via privacy lifecycle executor |
| workers (general/ai/pdf/maintenance) | read | none | write | write | write | none | none | maintenance worker deletes previews per retention sweep |
| backup process (cron on staging VM) | none | none | none | none | none | none | **write + read-back for checksum verification** | none |
| restore drill (`scripts/run_restore_drill.py` context) | none | none | none | none | none | none | read only | none |

### What R2 can and cannot enforce — be honest

**R2 API tokens scope per *bucket*, not per *prefix*.** There is no IAM-style
prefix condition on R2 S3 credentials. Consequently:

1. Any token scoped to `thesis-staging` with Object Read & Write can read,
   write, and delete **every prefix** in that bucket, including
   `manuscripts/` and `exports/`. The row-level matrix above is enforceable
   only by (a) separate buckets, or (b) app-layer discipline (which endpoints
   construct which keys — section 1 shows deletion is confined to
   `app/commercial/privacy.py`).
2. Web and workers share one credential *anyway* in this deployment:
   `deploy/compose.phase5.yml` feeds every service the same `env_file`, so
   `R2_ACCESS_KEY_ID` is identical across web-a/web-b and all workers.
   Splitting them means per-service env overrides — a compose change, out of
   scope for staging.

**Pragmatic split (recommended for staging):**

- **Token 1 — `thesis-staging-app`** (Object Read & Write, bucket
  `thesis-staging` only): goes into `${STAGING_ENV_PATH}` for the app stack.
  Bucket-wide within staging; accepted, with app-layer discipline as the
  prefix-level control.
- **Token 2 — `thesis-staging-backup`** (Object Read & Write, bucket
  `thesis-staging` only): held only by the backup cron user on the staging VM
  (separate credentials file, chmod 600, e.g. an `aws` CLI profile
  `r2-staging-backup`), never present in the app containers' env. This
  satisfies "application and backup credentials are separate and
  least-privilege" from `docs/runbooks/backup-restore.md` at the credential
  level, though R2 cannot stop this token from touching non-backup prefixes.
- **Stronger option (more moving parts):** a second bucket
  `thesis-staging-backups` with Token 2 scoped to it alone — the only way to
  make backup credentials *provably* unable to touch manuscripts. Worth doing
  in production; for staging the two-token/one-bucket split is acceptable and
  is what `STAGING_PROVISIONING.md` §6 (backups under `backups/` in the
  staging bucket) already assumes. If you choose the second bucket, move the
  `expire-staging-backups` rule there and drop it from `thesis-staging`.
- Restore drills reuse Token 2 read-side for staging (a third read-only token
  is defensible but disproportionate for a solo operator; revisit for
  production).

One more platform honesty note: `docs/runbooks/backup-restore.md` says "R2
versioning/retention is enabled for durable prefixes" — **R2 has no S3-style
bucket versioning**. The nearest control is R2 bucket locks (retention rules
that block deletion/overwrite for a period). Do not claim versioning in staging
evidence; if overwrite/delete protection for `manuscripts/` is wanted, evaluate
bucket locks separately (verify current capability in the Cloudflare docs
first) and record whatever is actually enabled.

---

## 6. Applying the lifecycle

From the repo checkout on the machine holding an admin-capable credential
(lifecycle changes need more than Object R/W — use the owner credential, not
the app token; the validation in section 7 confirms the app token cannot do
this):

```bash
ENDPOINT=https://CHANGE_ME_R2_ACCOUNT_ID.r2.cloudflarestorage.com

aws s3api put-bucket-lifecycle-configuration --bucket thesis-staging \
  --endpoint-url "$ENDPOINT" \
  --lifecycle-configuration file://deploy/r2-lifecycle-staging.json   # AFTER the file is updated per section 2

aws s3api get-bucket-lifecycle-configuration --bucket thesis-staging \
  --endpoint-url "$ENDPOINT"
# Expect exactly 5 rules: expire-previews(7), expire-temp(1), expire-failed(7),
# expire-staging-backups(30), abort-incomplete-multipart(1).
```

Wrangler equivalent: `wrangler r2 bucket lifecycle` subcommands exist
(`list`/`add`/`remove`), but the S3 `put-bucket-lifecycle-configuration` path
above is canonical for this repo because the reviewed JSON file is the source
of truth; check `npx wrangler r2 bucket lifecycle --help` before relying on
wrangler's flag syntax.

---

## 7. Validation commands (run after token + lifecycle are in place)

Prerequisite on the ARM64 staging VM — AWS CLI v2 aarch64 build:

```bash
curl -sS "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp && sudo /tmp/aws/install
aws --version   # aws-cli/2.x on aarch64
```

Configure the staging **app token** as a named profile (interactive prompts —
values never land in argv/history):

```bash
aws configure --profile r2-staging
#   AWS Access Key ID:     CHANGE_ME_STAGING_ONLY_TOKEN (from section 4)
#   AWS Secret Access Key: CHANGE_ME_STAGING_ONLY_TOKEN
#   Default region name:   auto
#   Default output format: json
ENDPOINT=https://CHANGE_ME_R2_ACCOUNT_ID.r2.cloudflarestorage.com
P="--profile r2-staging --endpoint-url $ENDPOINT"
```

### 7.1 Basic round-trip (rebuildable prefix)

```bash
echo "staging r2 validation $(date -u +%FT%TZ)" > /tmp/r2-check.txt

aws $P s3api put-object  --bucket thesis-staging \
  --key previews/validation/r2-check.txt --body /tmp/r2-check.txt
aws $P s3api get-object  --bucket thesis-staging \
  --key previews/validation/r2-check.txt /tmp/r2-check-back.txt
diff /tmp/r2-check.txt /tmp/r2-check-back.txt && echo "ROUND-TRIP OK"
aws $P s3api list-objects-v2 --bucket thesis-staging --prefix previews/validation/
```

### 7.2 Durable-prefix write + head (proves app token serves manuscript uploads)

```bash
aws $P s3api put-object  --bucket thesis-staging \
  --key manuscripts/validation/0000/original.docx --body /tmp/r2-check.txt \
  --content-type application/vnd.openxmlformats-officedocument.wordprocessingml.document
aws $P s3api head-object --bucket thesis-staging \
  --key manuscripts/validation/0000/original.docx
# Expect 200 with ContentLength and ETag; record the ETag in acceptance evidence.
```

### 7.3 Lifecycle is attached and correct

```bash
aws $P s3api get-bucket-lifecycle-configuration --bucket thesis-staging \
  || echo "NOTE: if this returns AccessDenied under the app token, run it with the owner credential — Object R/W tokens may not read bucket config, which is itself correct least-privilege."
# Under the owner credential: verify the 5 rule IDs from section 6 and that NO
# rule Prefix is manuscripts/, files/, exports/, originals/, revisions/,
# sealed/, or sources/.
```

### 7.4 Negative test — token cannot touch any other bucket

Create a throwaway bucket with the **owner** credential, then prove the staging
token is denied:

```bash
# Owner credential (dashboard or wrangler): create thesis-staging-negcheck
npx wrangler r2 bucket create thesis-staging-negcheck

# Staging app token must be denied on it:
aws $P s3api list-objects-v2 --bucket thesis-staging-negcheck        # expect: AccessDenied
aws $P s3api put-object --bucket thesis-staging-negcheck \
  --key probe.txt --body /tmp/r2-check.txt                            # expect: AccessDenied

# And must not be able to administer anything:
aws $P s3api put-bucket-lifecycle-configuration --bucket thesis-staging \
  --lifecycle-configuration '{"Rules":[]}' 2>&1 | grep -qi denied \
  && echo "ADMIN DENIED OK (expected)"                                # Object R/W must not edit lifecycle

# list-buckets under a bucket-scoped token: expect AccessDenied or a listing
# excluding other buckets — either is fine; the AccessDenied on the throwaway
# bucket above is the authoritative negative proof.
aws $P s3api list-buckets || true

# Clean up throwaway bucket with the owner credential:
npx wrangler r2 bucket delete thesis-staging-negcheck
```

Repeat 7.4's `list-objects-v2`/`put-object` denials with the
`r2-staging-backup` profile if Token 2 was created, plus its positive check:

```bash
aws --profile r2-staging-backup --endpoint-url $ENDPOINT s3api put-object \
  --bucket thesis-staging --key backups/validation/probe.dump --body /tmp/r2-check.txt
aws --profile r2-staging-backup --endpoint-url $ENDPOINT s3api head-object \
  --bucket thesis-staging --key backups/validation/probe.dump
```

### 7.5 Cleanup of validation objects

```bash
aws $P s3api delete-object --bucket thesis-staging --key previews/validation/r2-check.txt
aws $P s3api delete-object --bucket thesis-staging --key manuscripts/validation/0000/original.docx
aws --profile r2-staging-backup --endpoint-url $ENDPOINT s3api delete-object \
  --bucket thesis-staging --key backups/validation/probe.dump 2>/dev/null || \
  aws $P s3api delete-object --bucket thesis-staging --key backups/validation/probe.dump
rm -f /tmp/r2-check.txt /tmp/r2-check-back.txt
```

Record command outputs (status lines and ETags only — never credentials) in
the staging acceptance evidence alongside the image digest per
`STAGING_PROVISIONING.md`.

---

## 8. Free-tier and platform limits — honest accounting

- **R2 free tier (per month, account-wide):** 10 GB-month Standard storage,
  1M Class A operations (writes/lists), 10M Class B operations (reads). Zero
  egress fees. Staging fits comfortably: pilot manuscripts are ≤25 MB each
  (nginx `client_max_body_size 25m`), previews expire at 7d, and 30 daily
  `pg_dump` backups of a pilot-size database are megabytes each. The realistic
  way to breach free tier is a runaway preview/export loop — Class A ops, not
  storage; the UAT/perf scripts (`run_uat_flows.py`, `run_local_perf.py`) stay
  orders of magnitude below 1M ops.
- **Lifecycle granularity:** rules run about once a day and take effect from
  object creation time; a "1 day" rule means "deleted at the next daily pass
  after 24h", not exactly-24h.
- **No prefix-scoped credentials** (section 5) and **no S3-style bucket
  versioning** (section 5, honesty note). Don't copy S3 assumptions into
  evidence documents.
- **Location hints are hints.** `apac` placement is best-effort; R2 makes no
  data-residency promise for staging. If an institution contract later demands
  residency, that is a production design question (R2 jurisdiction features /
  different storage), not a staging setting.
- **Bucket count and token count** are not meaningful constraints at this
  scale.

---

## 9. Acceptance checklist (staging R2 done when all true)

| # | Check | Evidence |
|---|---|---|
| 1 | Bucket `thesis-staging` exists, APAC hint, no public access | dashboard screenshot or `wrangler r2 bucket list` output |
| 2 | `deploy/r2-lifecycle-staging.json` updated to section 2's corrected JSON (adds `expire-failed`, fixes `_comment`) and applied | `get-bucket-lifecycle-configuration` output showing 5 rules |
| 3 | No lifecycle rule matches `manuscripts/`, `files/`, `exports/`, or any reserved durable prefix | same output, manually verified |
| 4 | Token `thesis-staging-app` — Object R/W, `thesis-staging` only — installed in `${STAGING_ENV_PATH}` (`R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY`), chmod 600 | `scripts/verify_phase5_environment.py --target staging` passes; no secrets in evidence |
| 5 | Token `thesis-staging-backup` created and stored only in the backup cron profile | profile file exists, mode 600, absent from app env |
| 6 | Round-trip, durable write+head, and both negative tests pass (section 7) | command transcripts (redacted) |
| 7 | Prefix mismatch acknowledged: evidence cites this doc + `DATA_INVENTORY.md` caveats 1–2; code-prefix rename tracked as a separate post-staging task | link in acceptance notes |
| 8 | Production untouched: no production bucket or token created | assertion in acceptance notes |
