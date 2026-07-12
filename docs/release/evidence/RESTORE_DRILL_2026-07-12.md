# Restore Drill Evidence — 2026-07-12 (local proof of mechanism)

Instantiates `docs/release/RESTORE_DRILL_EVIDENCE.md`. **Environment:
local-development-macos.** This drill proves the automation and verification
mechanics end-to-end on real Postgres; the **staging restore drill remains
BLOCKED** (no staging infrastructure — see `docs/release/STAGING_BLOCKERS.md`)
and production RPO/RTO claims may not be derived from these numbers.

## Drill identity

- Drill ID: `c501ddd1f0` (second run; first run `10c10a18ac` proved repeatability)
- Date/time: 2026-07-12 (~04:25 UTC)
- Operator: automated (`scripts/run_restore_drill.py`), supervised by Claude session for Febin William
- Release SHA: branch state containing `81c9b6a` (post-RC `0941ebd`)
- Backup record: fresh `pg_dump` of `thesis_studio` (:5452), 257,145 bytes
- Backup encryption/key reference: none — local drill only (staging drills must encrypt off-host per `docs/runbooks/backup-restore.md`)
- Isolated restore environment: database `thesis_restore_drill` on the same local server, dropped after verification

## Targets

- Declared DB RPO/RTO (production targets): 15 min / 120 min
- Measured (local, tiny dataset): **RPO 0.0 s** (fresh dump; write→dump gap ~0.13 s) · **RTO 1.197 s** (dump 0.108 + createdb + restore 0.559 + `alembic current` + verification)
- Object inventory: local `var/storage` drill objects, checksummed before/after
- Sealed submission for checksum proof: synthetic sealed `SubmissionPackage` created through the production code path (`app/collaboration/sealing.py`)

## Procedure and evidence (24/24 checks passed)

Seeded via the app's own ORM and real code paths (canonical document built by
`apply_payload`, snapshot via `editor_service.create_snapshot`, attestation +
sealing via `sealing.seal_submission` — checksums come from production code,
not hand-rolled fixtures). Verified on the restored database: per-table row
counts vs pre-dump baseline (86 tables); `alembic current` = `0018 (head)`;
institution/membership/project fingerprints (roles, status, capabilities,
content flags) identical; canonical document SHA-256 identical (recomputed via
`app.collaboration.workflow.canonical_checksum` on the restored row); sealed
`package_checksum` identical AND recomputed from the restored manifest; sealed
`document_checksum` == snapshot checksum; `manuscript_revisions.checksum`
matches the on-disk object SHA-256; jobs restored with 0 running rows and 0
stale leases (same predicate as `job_queue._recover_expired_leases`); storage
inventory unchanged. Restore DB dropped afterwards (verified against
`pg_database`). Safety guard live-tested: `--source-db postgres` and an
injection-shaped name both refused (exit 2, zero side effects).

Tooling note: `docker exec` was broken machine-wide during the run (Docker
Desktop runc error, recorded in evidence `tooling`); the script fell back to
host `pg_dump 16.13` over TCP — matching the server major version.

## Results

- Database restored: yes · Schema expected/actual: `0018` / `0018 (head)`
- Sealed checksum expected/actual: identical (both package and document)
- Missing objects: 0 · Broken foreign references: 0
- RPO result: 0.0 s (local) · RTO result: 1.197 s (local; not representative — staging must re-measure with production-sized data)
- Defects: none in drill mechanics
- Evidence links: `RESTORE_DRILL_LOCAL_RAW.json` (machine-readable, both runs)
- **Outcome: pass (local mechanism) — staging drill: blocked**
- Reviewer: pending human review
