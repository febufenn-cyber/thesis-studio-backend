# Restore Drill Evidence

A backup is not accepted as recoverable until this record is completed in an isolated environment.

## Drill identity

- Drill ID:
- Date/time:
- Operator:
- Release SHA:
- Backup record ID:
- Backup creation time:
- Backup encryption/key reference:
- Isolated restore environment:

## Targets

- Declared database RPO:
- Measured database RPO:
- Declared database RTO:
- Measured database RTO:
- Object-storage inventory snapshot:
- Sealed submission selected for checksum proof:

## Procedure and evidence

- [ ] Restore PostgreSQL without access to production application credentials.
- [ ] Run `alembic current` and confirm expected schema.
- [ ] Verify institution, membership and project counts.
- [ ] Verify original manuscript and active revision references.
- [ ] Verify source, quotation, approval and audit records.
- [ ] Verify sealed submission package references.
- [ ] Restore or access required durable R2 objects.
- [ ] Recalculate the selected sealed DOCX/PDF checksum.
- [ ] Compare it with the recorded manifest checksum.
- [ ] Start an isolated application instance against the restored data.
- [ ] Run read-only smoke tests and one rebuildable preview regeneration.
- [ ] Confirm queued/running jobs are recovered without duplicate side effects.

## Results

- Database restored: `yes | no`
- Schema expected/actual:
- Sealed checksum expected/actual:
- Missing objects:
- Broken foreign references:
- RPO result:
- RTO result:
- Defects and corrective actions:
- Evidence links:
- Outcome: `pass | conditional | fail`
- Reviewer:

Never run an untested restore command against production. A failed or incomplete drill blocks external recovery claims.
