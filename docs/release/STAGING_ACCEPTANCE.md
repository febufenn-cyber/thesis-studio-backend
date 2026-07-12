# Staging Acceptance Evidence

Complete this record for one exact validated release SHA. Attach links to retained CI artifacts, screenshots, logs and drill records. Do not mark a row complete from memory.

## Release identity

- Release SHA:
- Validation attestation: `release-candidates/<sha>.json`
- Container digest:
- Schema version:
- Renderer version:
- Prompt bundle version:
- Staging URL:
- Test date and operator:

## Infrastructure

- [ ] Two web instances are healthy behind health-aware routing.
- [ ] PostgreSQL is external to the application host and TLS is confirmed.
- [ ] R2 credentials are least-privilege and staging-specific.
- [ ] General, AI, PDF and maintenance workers are independently running.
- [ ] ClamAV is healthy and not reachable from the public internet.
- [ ] Email uses a staging-safe recipient policy.
- [ ] Billing uses sandbox/manual test data only.
- [ ] AI uses a commercial test provider or is explicitly disabled.
- [ ] `/healthz`, `/readyz`, `/status` and `/meta/release` pass the smoke script.

## User journeys

- [ ] Student identity, session listing and session revocation.
- [ ] Manuscript upload, malware scan, checksum and immutable revision.
- [ ] Import report and unsupported-content review.
- [ ] Structured edit, autosave, conflict response, undo and restore.
- [ ] Source/quotation verification and exact citation resolution.
- [ ] Authoritative PDF preview and stale-preview regeneration.
- [ ] Grounded AI proposal with partial acceptance and provenance.
- [ ] Supervisor snapshot review, comment, suggestion and decision.
- [ ] Operator formatting correction without academic prose authority.
- [ ] Separate academic, citation, formatting and institutional approval.
- [ ] Final verifier pass and sealed submission package.
- [ ] Recipient-bound external examiner access and revocation.
- [ ] Data export, deletion grace period and sealed-custody restriction.
- [ ] Metadata-only support diagnostic and failed-job retry.

## Failure exercises

- [ ] Stop the AI provider: editing/export remain available and status reports AI degradation.
- [ ] Stop one web instance: traffic continues through the other instance.
- [ ] Kill the PDF worker mid-job: another worker reclaims the expired lease without duplicate output.
- [ ] Stop ClamAV: uploads fail with 503 while existing projects remain usable.
- [ ] Use a stale document version: mutation returns 409 and preserves both users' work.
- [ ] Revoke a staff member: old sessions and invitation links fail opaquely.
- [ ] Restore backup into isolation and compare sealed-submission checksum.

## Result

- Blocking defects:
- Non-blocking defects:
- Evidence links:
- Decision: `pass | conditional | fail`
- Approved by:
- Approved at:
