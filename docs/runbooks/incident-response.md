# Incident Response Runbook

## Purpose

Protect academic work, contain failures quickly and communicate honestly. Do not include thesis text, quotations, private AI prompts or full email addresses in incident channels.

## Severity

### SEV-1

- Cross-tenant exposure or credible access-control bypass
- Irrecoverable or potentially widespread data loss
- Compromised session, database, storage or billing signing secret
- Widespread authentication failure
- Incorrect deletion of durable/sealed material

Immediate actions:

1. Name incident commander, technical owner and communication owner.
2. Freeze deployments and preserve evidence.
3. Disable affected tenant, feature, provider or credential at the narrowest safe boundary.
4. Revoke/rotate compromised sessions and secrets.
5. Record affected release SHA, schema version, institution IDs and hashed account/project identifiers.
6. Start customer communication after facts are verified; do not speculate.
7. Engage qualified legal/privacy counsel for suspected personal-data breach.

### SEV-2

- Export/PDF unavailable for multiple customers
- AI unavailable globally while deterministic functions remain healthy
- Major institution blocked
- Billing incorrectly disabling valid customers
- Restore or backup verification failure

Contain by isolating the component, opening circuits, pausing entitlement enforcement where contractually safe, or routing to another worker/provider.

### SEV-3

- Single-project failure
- Isolated preview or email delivery problem
- One expired invitation or recoverable job failure

Handle through audited support tooling and normal support communication.

## Required incident record

- Severity and component keys
- Start, detection and containment times
- Release SHA and deployment record
- Institutions affected
- User/project identifiers as hashes unless direct identification is operationally necessary
- Data classes involved
- Containment actions
- Customer updates
- Recovery evidence
- Root cause and contributing controls
- Corrective actions, owners and deadlines

## Component status

Report separately:

- Web application
- Authentication
- Editing
- AI assistance
- Manuscript ingestion
- Preview/PDF
- Downloads
- Email

AI degradation must not be presented as whole-platform downtime when editing/export remain healthy.

## Evidence preservation

Retain metadata-only request traces, release/deployment records, billing event hashes, session revocations, job leases, object checksums and database audit events. Do not copy manuscript content into tickets unless explicit, time-limited support access was granted and content is essential.

## Closure

An incident is resolved only after service restoration is verified, affected customers receive an accurate update, required notifications are assessed and the post-incident review has owners for corrective work.
