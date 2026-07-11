# Backup and Restoration Runbook

## Recovery classes

| Artifact | Example internal target | Restore evidence |
|---|---:|---|
| PostgreSQL | RPO 15 minutes, RTO 2 hours | Schema, memberships, projects, approvals, billing and audit queries pass |
| Original manuscripts | Near-zero RPO, RTO 4 hours | Object checksum and database reference resolve |
| Canonical snapshots | RPO aligned with database | Document checksum/version match |
| Sealed submissions | Near-zero RPO | Package and document checksums match exactly |
| Institution profiles/policies | RPO aligned with database | Published/pinned versions resolve |
| Previews/temp files | Rebuildable | Regeneration succeeds; no restore required |

These are internal targets until measured and contractually approved.

## Backup prerequisites

- Database backups are encrypted and stored off the application host.
- R2 versioning/retention is enabled for durable prefixes.
- Backup encryption keys have documented owners and a tested recovery path.
- Application and backup credentials are separate and least-privilege.
- Backup records store checksum, scope, time, release and schema metadata—not secrets.

## Before a risky migration

1. Confirm the exact release SHA and migration range.
2. Create/verify a recent database backup.
3. Record backup evidence in the protected production environment.
4. Run `alembic upgrade head`, `downgrade <previous>`, `upgrade head` against the release-validation database.
5. Review migration locks, backfills and rollback compatibility.
6. Prefer expand–migrate–contract; destructive contract steps ship later.

## Restore drill

1. Select a completed encrypted backup.
2. Create an isolated restore target with no production egress.
3. Restore PostgreSQL and required durable objects.
4. Run migrations only according to the backup's recorded schema/release.
5. Verify:
   - institution and department isolation
   - project ownership/memberships
   - canonical versions and snapshots
   - source/quotation verification
   - approvals/review cycles
   - sealed package and document checksums
   - billing event/subscription state
   - job queue safety (running leases are not blindly resumed)
6. Record restored checksum, duration, evidence and pass/fail through the recovery API.
7. Destroy the isolated restore target according to retention policy.

## Failure handling

A green backup job is insufficient. A failed checksum, unresolved R2 reference, missing encryption key, failed membership link or exceeded RTO fails the drill. Open a reliability incident, preserve evidence and do not advertise the target as achieved until a later drill passes.

## Host replacement exercise

At least periodically:

1. Build a fresh application host from the immutable release image.
2. Inject secrets from the protected store.
3. Connect to isolated PostgreSQL/R2.
4. Start web and queue-specific workers.
5. Run the release-aware smoke test.
6. Verify an expired job lease is reclaimed by another worker.
7. Confirm support can inspect safe metadata without reading a manuscript.

No undocumented founder-only step may be required for success.
