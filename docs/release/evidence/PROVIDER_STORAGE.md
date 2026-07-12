# Provider Readiness — Object Storage (Cloudflare R2)

Date: 2026-07-12 · Commit `7397fdc`

## Validated (real, local)

- **Adapter**: `app/services/storage_service.py` — R2 (boto3 S3-compatible,
  presigned URLs) and local filesystem backends; `STORAGE_BACKEND=auto` selects
  R2 only when all four credentials are present and non-placeholder.
- **Production fail-closed**: `ENV=production` + `PRODUCTION_REQUIRE_R2` rejects
  `STORAGE_BACKEND!=r2` and placeholder credentials — verified in this
  validation (negative test rc 1) and by CI's production config safety test.
- **Readiness**: storage component check validates R2 credential completeness,
  or local-path writability with ≥500MB free (`app/services/readiness_service.py`).
- **Durable-prefix policy** documented in `docs/phase5/data-map.md`
  (`originals/ revisions/ sealed/` durable; `previews/ temp/` rebuildable).

## Blocked (external) — R2 is entirely unprovisioned

| Item | Status / unblock |
|---|---|
| Staging bucket + least-privilege token | No bucket exists; `.env`s carry placeholders. Create bucket `thesis-staging`; API token scoped Object R/W to that bucket only (steps in `STAGING_BLOCKERS.md` §6). |
| Encryption | R2 encrypts at rest by default; record account-level confirmation once the bucket exists. |
| Lifecycle rules (previews/temp expiry, incomplete-multipart abort) | Cannot be configured without the bucket. Required rule set is specified in `docs/phase5/data-map.md`; verify none touch durable prefixes before enabling. |
| Object inventory snapshot for restore drills | Blocked on bucket. |

## Non-conformance note

The v1 production VM currently runs `STORAGE_BACKEND=local`. That is
explicitly prohibited for phase-5 production (`production-topology.md`
boundary 2; enforced by the config validator). Local mode remains acceptable
only for development.
