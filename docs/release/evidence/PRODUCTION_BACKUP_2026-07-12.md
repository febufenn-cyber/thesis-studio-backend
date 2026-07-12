# Production Backup — v1 thesis_studio — 2026-07-12

Non-destructive, verified backup of the **live v1 production database** taken
before any change. No prior backup existed. No secrets, no user data values.
Companion: `PRODUCTION_BACKUP_2026-07-12.json`.

## Backup

| Field | Value |
|---|---|
| Database | `thesis_studio` (on-host PostgreSQL 14.23) |
| Method | `pg_dump -Fc` (custom format), read-only |
| Artifact | `/opt/thesis-studio-backend/backups/predeploy-thesis_studio-20260712T125345Z.dump` |
| Size | 35,242 bytes |
| SHA-256 | `aef65262e1e86694199938719da7ef834aea6ae16f69299556c9fb2e0365cdf8` |
| Location | Durable host path, **outside** any container volume |

## Verification (non-destructive — never restored over production)

- Restored **schema only** into an isolated temporary database
  `thesis_predeploy_verify` → **14 tables** materialised successfully.
- Temporary verification database **dropped** after the check.
- Live production **alembic revision: `0006`** (confirmed against the running DB).
- Live row counts (counts only, no data): institutions 4, users 2, sessions 4,
  files 0, messages 6.

The dump is readable, restores cleanly to a schema, and reflects the expected
v1 structure. Backup verification: **PASS**.

## Rollback anchor

This backup is the restore point if any future production change goes wrong.
Restore procedure (into an isolated DB first, never over live production):

```bash
createdb thesis_studio_restore
pg_restore -d thesis_studio_restore \
  /opt/thesis-studio-backend/backups/predeploy-thesis_studio-20260712T125345Z.dump
# verify, then promote only after an explicit, separate decision
```

Rollback owner: Febin (repository/host owner).

## Note

No migration was run and no cutover was performed in this mission (see
`PRODUCTION_BLOCKERS.md`). This backup stands purely as a safety artifact and
as proof that the backup+verify path works against the real production DB.
