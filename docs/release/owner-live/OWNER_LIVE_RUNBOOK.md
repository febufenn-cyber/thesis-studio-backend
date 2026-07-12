# Owner-Live Deployment Runbook — thesis.robofox.online

**OWNER-ONLY PRIVATE LIVE DEPLOYMENT — NOT COMPLIANT PRODUCTION, NOT STAGING,
NOT institution-ready.** A single-user deployment on a constrained 1 GB shared
host, with the owner's explicit acceptance of the documented deviations. No
secrets, IPs, or private data appear in this file; full operational evidence
is kept privately on the host.

## Accepted deviations (owner-authorised)

Shared 1 GB x86_64 host · on-host PostgreSQL 14 · local durable storage ·
**no ClamAV / no malware scanning** · no R2 · one web + one worker · host
networking to reach the shared PG over loopback (avoids restarting the shared
DB server) · AI disabled · billing manual · trusted owner-uploaded documents
only. Edge access is additionally restricted to the owner (Phase 9).

## Not acceptable (hard rails honoured)

No data loss · legacy `thesis_studio` DB never overwritten or deleted · no
destructive migration without a full-data rehearsal first · no debug codes or
secrets exposed · co-tenant services never broken · legacy v1 deployment kept
intact as the rollback target.

## Components

- `deploy/compose.owner-live.yml` — web + worker, host networking, digest image,
  loopback `:8400`, mem caps, no ClamAV/PG/tunnel containers.
- `.env.owner-live.example` — owner-live config template (real file lives on
  the host, chmod 600, outside Git).
- Dedicated database `thesis_studio_v2` (legacy `thesis_studio` untouched).
- Dedicated storage `/opt/thesis-studio-v2/var`.
- `DB_POOL_SIZE=2 / DB_MAX_OVERFLOW=2` (new env option; app defaults stay 10/20).

## Deploy sequence (executed by the mission)

1. Derive the eligible SHA: `python scripts/latest_attested_release.py`.
2. Build the exact release: `gh workflow run phase5-release.yml -f environment=build-only -f expected_sha=$SHA`; record the amd64 digest from the manifest artifact.
3. Fresh full backup of `thesis_studio` (`pg_dump -Fc`) + encrypted second copy.
4. Full-data restore rehearsal into `thesis_studio_v2_rehearsal`; verify rows/FKs.
5. Rehearse migration 0006→0018 revision-by-revision on the rehearsal DB, then boot the app against it.
6. Create `thesis_studio_v2`, restore the backup, run the identical migration.
7. Storage migration (none: legacy had no files).
8. Owner-live env with fresh v2 secrets (JWT, billing webhook); reuse the domain's Resend + Google config.
9. Owner-only edge access (Cloudflare Access preferred; else nginx basic auth).
10. Stop the `thesis-demo-*` stack to free memory; start v2 on `:8400`.
11. Private canary smoke on `127.0.0.1:8400`.
12. Atomic nginx switch `:8000 → :8400`, reload, public verify.

## Rollback (any failure)

Point nginx back to `127.0.0.1:8000`, `nginx -s reload`, verify legacy v1
health. Leave the v2 DB and containers intact for investigation. **Never**
restore over the legacy database; never delete the backup. Because the
migration only adds tables (expansion), the legacy DB remains a valid rollback
source untouched by the v2 work.

## Malware scanning

**DISABLED by owner-only exception.** No scanning is performed or claimed.
EICAR is recorded as SKIPPED, never passed. Only trusted owner documents.
