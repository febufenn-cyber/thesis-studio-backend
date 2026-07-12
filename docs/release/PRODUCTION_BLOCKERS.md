# Production Cutover Blockers — thesis.robofox.online

Date: 2026-07-12 · Eligible release: `69d5333c059731d8b040171bc0754df951407171`

**Outcome: BLOCKED — PRODUCTION INFRASTRUCTURE INCOMPLETE.** The release is
merged, attested (174/0/0/0) and imaged for amd64+arm64. It was **not** cut
over to production, because the Phase 5 production contract cannot be
satisfied on the current host without disguising the deployment (which the
mission forbids). Every safe, authorised action was completed first:
pre-deploy state capture, PR #9 review + merge + attestation, and a verified
v1 database backup. Nothing on production was changed, deleted, or degraded.

## Hard blockers (each independently prevents a compliant cutover)

### 1. ClamAV — mandatory, absent, and cannot fit
Production requires `MALWARE_SCAN_MODE=clamav` + `PRODUCTION_REQUIRE_MALWARE_SCAN=true`;
the config validator **fails closed** without a reachable scanner. No ClamAV
exists on the host. ClamAV holds ~1.5–3 GB of signatures resident — the host
has **~318 MB RAM available**. Physically impossible here.
**Unblock:** a host (or sidecar host) with ≥4 GB RAM running the pinned
`clamav/clamav:1.4.5@sha256:86c2a503…` internal-only, per `deploy/compose.phase5.yml`.

### 2. Durable R2 object storage — not provisioned/validated
Production requires `STORAGE_BACKEND=r2` + `PRODUCTION_REQUIRE_R2=true` with
non-placeholder, production-scoped credentials. The live host runs
`STORAGE_BACKEND=local`; there is no verified R2 bucket with a successful
test write. **Unblock:** create the production R2 bucket + least-privilege
token and validate a write (steps in `docs/release/staging/R2_STAGING_SPEC.md`,
adapted to a `thesis-prod` bucket).

### 3. Host capacity — cannot run the topology beside co-tenants
956 MB RAM / 2 shared vCPU already runs v1 + LeadFinder + NetPrep + FoxLabel +
Voice + clothing + marketing + the E2 demo. The Phase 5 stack (2 web +
general/ai/pdf/maintenance workers + ClamAV + LibreOffice) needs multiple GB.
Safety rule 6/11: co-tenant production services must stay healthy — they
cannot. **Unblock:** a dedicated production host (the A1 spec in
`docs/release/staging/OCI_A1_STAGING_SPEC.md` sizing applies).

### 4. PostgreSQL — v1 is 14 on-host; production wants 16, TLS if networked
Live DB is PostgreSQL **14.23** on `localhost`. The contract wants 16 with TLS
for any networked/off-host DB. **Unblock:** provision PG16 (isolated per the
production-topology rules; `docs/release/staging/POSTGRES_STAGING_SPEC.md`).

### 5. Migration scope — 0006 → 0018 is not a single-canary change
Live production is at alembic **`0006`**; the release is **`0018`**. Cutover
would run the entire **Phase 1–5 schema evolution (0007→0018, 12 revisions)**
against real user data in one step. That exceeds a reversible canary's safe
scope and needs its own staged, backed-up migration plan with per-revision
validation. **Unblock:** a dedicated migration runbook exercised first on a
0006-seeded copy in staging.

## What IS ready (so the remaining work is scoped)

- Eligible attested application release with a reproducible amd64+arm64
  manifest and digest evidence.
- Protected `production` GitHub environment (required reviewer + protected
  branches) — the human approval gate exists.
- Email provider (Resend) live and verified.
- A **verified v1 production backup** now exists (`PRODUCTION_BACKUP_2026-07-12`)
  — the rollback anchor that did not exist before.
- Official release workflow (`phase5-release.yml`) with a production job that
  enforces attestation, backup evidence, and canary→rolling steps.

## The compliant path (owner decisions)

1. Stand up a dedicated production host (≥4 GB RAM) — not the shared 956 MB VM.
2. Provision isolated PG16 (+TLS) and a production R2 bucket + scoped token.
3. Deploy internal ClamAV (pinned).
4. Author and rehearse a 0006→0018 migration runbook on a staging copy.
5. Set the production environment secrets; run
   `verify_phase5_environment.py --target production` until it passes.
6. Dispatch `phase5-release.yml -f environment=production -f expected_sha=$(python scripts/latest_attested_release.py)`
   through the protected environment (owner approves), which performs the
   backup-evidence check + canary + rolling cutover with rollback intact.

Until steps 1–5 exist, a cutover would only be possible by faking it
(`ENV=development`, `STORAGE_BACKEND=local`, `MALWARE_SCAN_MODE=disabled`) —
which is exactly the E2 **demo** configuration and is explicitly not a
production deployment.
