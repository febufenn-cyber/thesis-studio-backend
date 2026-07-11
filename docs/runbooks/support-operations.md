# Support Operations Runbook

## Principle

Support resolves operational failures without default access to thesis content. Every sensitive action requires a capability, justification and audit record.

## Supported actions

- Find an account by exact identity through authorized tooling
- View institution, role, project state, release and document-version metadata
- Check ingestion, AI, preview, export and lifecycle job state
- Retry an idempotent failed job
- Reissue or revoke an invitation
- Review billing subscription and entitlement state for the same institution
- Revoke device sessions
- Disable AI or reduce a tenant budget during abuse/cost incidents
- Generate a metadata-only diagnostic bundle
- Guide a user to restore a canonical snapshot

## Actions support must not perform by default

- Read thesis chapters, sources, quotations or private AI conversations
- Modify academic prose
- Approve academic, formatting or submission decisions
- Change institutional policies without the institution administrator
- Bypass billing or retention controls through direct database access
- Claim that an electronic workflow approval is a legal signature

## Diagnostic workflow

1. Record the support ticket and customer-reported symptom.
2. Confirm the institution and project through opaque identifiers.
3. Obtain time-limited support access or use an existing metadata-only grant.
4. Generate the diagnostic bundle.
5. Check release SHA, document version, profile/policy versions, job queue, attempts, lease, worker, checksums and object presence.
6. Retry only failed/cancelled idempotent jobs.
7. If content is genuinely necessary, request explicit user/institution consent, narrow the scope and show a persistent support-access banner.
8. Record the result and revoke/expire access.

## Billing support

- Verify the signed event is present and tenant-bound.
- Compare event time with subscription `last_event_at`.
- Replay only the institution's own failed/ignored event after fixing the cause.
- Use manual entitlement grants for documented procurement contracts, promotions or temporary recovery—not as an undocumented permanent workaround.
- Grants require a reason, source reference, actor and optional expiry.
- Tax/GST treatment requires qualified accounting review.

## Failed export

1. Confirm canonical document version and profile/renderer/release versions.
2. Confirm verifier state and whether the export is draft or final.
3. Inspect PDF queue age, attempts, worker lease and error class.
4. Retry the same idempotent job or request a new export only when the document changed.
5. Do not download the thesis unless explicit content access is granted.

## Session compromise

- Revoke the affected device or all sessions.
- Suspend compromised membership when institution authority permits.
- Require reauthentication before restoring sensitive access.
- Open SEV-1 when a signing secret or broad account compromise is suspected.

## Escalation

- Cross-tenant indication, deletion error or compromised secret: SEV-1
- Institution-wide export, auth, billing or AI outage: SEV-2
- Single-project recoverable failure: SEV-3

Support is not 24/7 unless staffing and the customer contract explicitly say so.
