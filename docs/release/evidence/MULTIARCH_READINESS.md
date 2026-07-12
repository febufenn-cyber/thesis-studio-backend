# Multi-Architecture ARM Staging Readiness — Evidence

Date: 2026-07-12 · Branch: `agent/multiarch-arm-staging`
Base main SHA: `e133f27afc0ed40ce2056d47141924c53af68ac9`
Newest eligible attested application release at time of writing: `9814c0a44f4227ed21dbd4df9d0dbc3634125d30`
(derived by `scripts/latest_attested_release.py`, which skips attestation-only commits)

## Validation matrix (branch HEAD, local unless stated)

| Check | Result |
|---|---|
| pytest | **174 passed / 0 failed / 0 errors / 0 skipped** |
| compileall + app import | pass |
| JS syntax ×8 | pass |
| bandit `-r app -x tests -ll -ii` | pass |
| pip-audit (installed clean env) | no known vulnerabilities |
| secret-pattern scan | pass |
| alembic head → 0016 → head | pass; current `0018` |
| OpenAPI | 176 paths |
| env verifier hardening | CI-synthetic positive rc 0; `CHANGE_ME` negative rc 1; missing-TLS negative rc 1 |

## Architecture results — what ran where (honest split)

| Item | Architecture | Where | Result |
|---|---|---|---|
| Container runtime smoke (15 checks) | **arm64 (native)** | Apple Silicon / colima, this branch's image | **15/15 PASS** (`ARM64_RUNTIME_SMOKE_LOCAL.json`) |
| — includes | | | fail-closed prod boot; non-root 10001; imports; LibreOffice 7.4.7.2; **Times New Roman present → /readyz pdf_stack true in-container for the first time**; ClamAV protocol; alembic 0018; healthz; release identity; all readyz components; worker loop; DOCX render; PDF conversion (32,926 bytes) |
| Python test suite | amd64-equivalent (darwin/arm64 host venv) | local | 174/0/0/0 |
| amd64 image build + runtime smoke | amd64 (native) | CI `multiarch-validation.yml` on this PR | produced by CI — not claimed locally |
| Multi-arch manifest build/push + digest evidence | both | `phase5-release.yml` at dispatch time | produced at release time (local docker lacks buildx; not claimed) |

Local arm64 image id: `sha256:c3b91d284ade…` built from this branch with
`RELEASE_SHA=9d071a18e1e7e550a0e897653c85921c60076e91` baked. Manifest and
per-platform digests are recorded by the release workflow's
`release-image-manifest-<sha>` artifact when a release is dispatched — no
manifest exists yet because no release has been dispatched from this branch.

## Defects found and fixed on this branch

1. **Image could never pass `/readyz` in any container deployment** —
   `pdf_stack` requires Times New Roman; image had only Liberation. Fixed via
   `ttf-mscorefonts-installer` (contrib, EULA pre-accepted, arch-independent),
   proven by the arm64 smoke (`fonts` and `readyz` checks).
2. **deploy-staging never migrated the real staging database** — the verify
   job's alembic runs against the throwaway CI DB only; first deploy would
   fail readiness on schema mismatch. Expand-migrate step added before `up -d`.
3. **Env verifier fail-open gaps** — accepted `CHANGE_ME` placeholders and
   only warned on missing DB TLS; both now fail closed (re-verified against
   the CI synthetic env).
4. **Lifecycle rules targeted aspirational prefixes** — corrected to the
   prefixes code actually writes (`manuscripts/ files/ exports/ previews/`),
   `failed/` expiry added, durable prefixes provably unmatched.

## Release discipline

- Active ruleset `18827479`: force-push and deletion of main blocked (verified).
- Ruleset `18827483` (PR + required checks `validate`,`security`, strict):
  created but **disabled** — GitHub rejects the Actions integration as a
  bypass actor on user-owned repos, and activating would break the
  attestation workflow's push. Upgrade paths in
  `docs/release/BRANCH_PROTECTION_BLOCKERS.md`. Direct-push finding for
  `9814c0a` documented there.
- Release workflow now rejects attestation-only commits as deploy targets and
  requires the manifest to contain both `linux/amd64` and `linux/arm64`.

## Secret and configuration classification (Subphase G)

| Class | Items |
|---|---|
| GitHub environment secrets (staging) | STAGING_HOST, STAGING_USER, STAGING_SSH_KEY, STAGING_ENV_PATH, STAGING_DEPLOY_PATH, STAGING_BASE_URL, CLAMAV_IMAGE (**set** — pinned public ref) |
| Repository-level secret | RELEASE_VALIDATION_DATABASE_URL |
| Host environment values (staging `.env`) | DATABASE_URL, JWT_SECRET, R2_*, RESEND_API_KEY, PRIVACY_HASH_PEPPER, BILLING_WEBHOOK_SECRET, BACKUP_EVIDENCE_PATH |
| Public configuration | ENV=staging, AI_GLOBAL_ENABLED=false, BILLING_PROVIDER=manual, STORAGE_BACKEND=r2, PRODUCTION_REQUIRE_R2=true, MALWARE_SCAN_MODE=clamav, PRODUCTION_REQUIRE_MALWARE_SCAN=true, schema/renderer/canonical/prompt versions |
| Immutable image references | ROBOFOX_IMAGE (digest-addressed from manifest evidence), CLAMAV_IMAGE `clamav/clamav:1.4.5@sha256:86c2a503…` |
| Nonexistent (documented, not invented) | `AI_COMMERCIAL_PROVIDER_READY` — no code binding; `AI_GLOBAL_ENABLED` is the enforced switch |

## Resource and deployment statement

- Cloud resources created: **none** (no VM launched, no DB, no bucket).
- Staging deployed: **no**.
- Production touched: **no** (no secrets, DNS, database, storage, services,
  or approval settings modified).
