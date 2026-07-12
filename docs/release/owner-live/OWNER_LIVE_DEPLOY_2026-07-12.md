# Owner-Live Deployment Record — 2026-07-12

**OWNER-ONLY PRIVATE LIVE DEPLOYMENT — NOT compliant production, NOT staging,
NOT institution-ready, NOT a security-validated multi-user system.** Deployed
with the owner's explicit acceptance of the documented single-user deviations.
No secrets, IPs, co-tenant names, or user data appear here; full operational
evidence is kept privately on the host (mode 600).

## Release

- Eligible SHA (derived, not hand-copied): `5401e26424383b5e903127e59f3d9e10b173f366`
- Attestation: `release-candidates/5401e26….json` (174/0/0/0, migration/security/image passed)
- Manifest: `sha256:efda7cfd033e9997d3f2b2cadb8824e14daa10c9ae9f21b4b0ad4d2a42f3b303`
- **Deployed amd64 digest**: `sha256:728a9f8b70a55f1a68de5552643015a4915c17614838bafab69bb2c73cc7ac45`
  (arm64 `sha256:db8bfb8f…` recorded, unused on this x86_64 host)
- Image embeds `RELEASE_SHA=5401e26…`, `BUILD_TIME=2026-07-12T13:24:00Z`, arch amd64.

## Backup (before any change)

- `pg_dump -Fc` of the legacy database, 35,242 bytes, sha256 `57da1b30…`.
- Second copy AES-256 encrypted (passphrase in a host 600 file, never printed);
  decrypts to identical sha256. **Host-loss protection incomplete** (both copies
  on the same host; no off-host destination available).
- PostgreSQL 14.23; legacy DB size ~9.4 MB; legacy alembic `0006`.

## Full-data restore rehearsal → PASS

Restored the full dump into an isolated `…_rehearsal` DB: all row counts matched
source (institutions 4, users 2, sessions 4, messages 6, auth_tokens 4, files 0,
projects 0), 14 tables, 0 invalid constraints.

## Migration rehearsal 0006 → 0018 → PASS

Applied every revision **one at a time** on the rehearsal DB; at each revision
the data invariant held exactly (institutions 4 / users 2 / messages 6, 0
invalid constraints). Final: alembic `0018`, 14 → 86 tables. App booted against
the migrated rehearsal DB: `/healthz` 200, `/readyz` 200 (all components),
`/meta/release` = exact SHA + schema `0018`.

## Final v2 database → PASS

`thesis_studio_v2` created from the same verified backup, identical migration to
`0018`; row counts match legacy; 86 tables; 0 invalid constraints.
**Legacy `thesis_studio` left UNTOUCHED at `0006` as the rollback source.**

## Storage migration

Legacy had **no** stored files (0 files/0 projects) — nothing to migrate.
Dedicated v2 path prepared (owned by the container runtime user, 700).

## Owner-live configuration

`ENV=development` (accepted designation), `DEBUG=false`, `AI_GLOBAL_ENABLED=false`,
`BILLING_PROVIDER=manual`, `STORAGE_BACKEND=local`, `MALWARE_SCAN_MODE=disabled`,
`PRODUCTION_REQUIRE_R2=false`, `PRODUCTION_REQUIRE_MALWARE_SCAN=false`,
`DB_POOL_SIZE=2`/`DB_MAX_OVERFLOW=2`. Fresh v2 JWT + billing-webhook secrets
generated on the host; domain Resend + Google client id reused. Env file 600,
outside Git.

## Owner-only edge access

Cloudflare Access credentials were not available, so **nginx Basic Authentication**
is the edge restriction (documented fallback), realm "owner only", password on a
host 600 file (never printed). The app's own authentication (incl. Google
sign-in, which the owner completes in a browser) remains enabled behind it.
`/.well-known/acme-challenge/` is exempt so certificate renewal survives.

## Canary + cutover

- Demo `thesis-demo-*` stack removed to free memory before start.
- v2 (web+worker) started on `127.0.0.1:8400` **in parallel** with legacy v1
  (`:8000`), host networking to reach on-host PostgreSQL over loopback (no
  restart of the shared DB server).
- Private canary smoke (`:8400`): healthz 200, readyz 200 (all components),
  identity `5401e26`/`0018`, migrated data visible, DEBUG=false, DOCX render +
  PDF conversion (Times New Roman present), worker running, ~441 MB RAM free,
  no OOM. **EICAR: SKIPPED — malware scanning disabled by owner-only exception.**
- Atomic nginx switch `:8000 → :8400` (config backed up, `nginx -t`, reload
  without connection drop).

## Public verification (https://thesis.robofox.online)

- No creds → **401** with owner realm (edge restriction active; no debug leak).
- With creds → healthz 200, readyz 200, `/meta/release` = `5401e26…` schema
  `0018`, root page = the new "Collaborative Academic Workspace" (not legacy v1,
  not demo). Cloudflare + valid TLS. acme path reachable without auth.

## Post-cutover

v2 containers: 0 restarts, no OOM. All co-tenant services online; co-tenant
public sites healthy. Memory ~376 MB free, swap moderate/stable. **No rollback
was required.**

## Rollback path (intact)

Point nginx back to `:8000` (backup config retained) and reload; legacy v1
(`:8000`) is running and its database is untouched at `0006`. The migration was
purely additive, so the legacy DB remains a valid rollback source. Never restore
over the legacy DB; never delete the backups.

## Known follow-ups / accepted risks

- Malware scanning absent — only trusted owner documents may be uploaded.
- Host-loss protection incomplete (no off-host backup destination).
- Single 1 GB shared host, on-host PostgreSQL 14, local storage — none of the
  compliant-production controls are claimed.
- LibreOffice emits benign "fontconfig cache" warnings under the read-only root
  filesystem; PDF output is correct. A writable fontconfig cache dir would
  silence them (non-blocking).
- Full authenticated end-user DOCX→PDF UI flow is the owner's to exercise via
  Google sign-in; the deployed image's render/PDF capability is proven above.
