# Phase 5 — Commercial Reliability, Security and Scale

## Promise

Robofox can serve paying students, operators and institutions reliably, securely and predictably, with controlled costs, recoverable infrastructure, contractual accountability and no dependency on one machine, one AI login or one founder's memory.

## Non-negotiable boundaries

- Application health and AI-provider health are independent.
- Entitlements are enforced by the backend, not by hidden frontend controls.
- Billing webhooks are verified, idempotent, replayable and never trusted from browser redirects.
- Institutional manual contracts may grant entitlements without an online subscription.
- Server-side sessions are revocable per device and per user.
- Production may not use local object storage fallback.
- Every release exposes safe build, schema, renderer and prompt-bundle identity.
- Logs may contain identifiers and hashes, but never thesis prose, quotations, full email addresses or private AI prompts.
- Durable artifacts and rebuildable artifacts have separate retention classes.
- Deletion is a lifecycle with auditable stages, not an instant UI claim.
- Backups count only after checksum-preserving restore drills pass.
- Support never receives manuscript content by default.
- No certification, legal-signature, uptime or no-data-loss claim is made without evidence and formal review.

## Product editions

### Student

One or a small number of active projects, bounded ingestion/export capacity, value-based AI review allowances, viva support and student-controlled collaboration.

### Professional operator

Multiple client projects, operator queues, reusable profiles, staff seats, branded handoff, higher upload/export limits and audited delivery.

### Institution

Cohorts, role workflows, versioned policy/templates, supervisor/operator seats, manual invoicing, retention controls, procurement evidence and support commitments.

## Runtime topology

Robofox remains a modular monolith, deployed as independently replaceable processes:

1. Web/API process
2. General background worker
3. Dedicated preview/PDF worker
4. Scheduled maintenance process

Queue payloads are durable and idempotent. A worker crash must not lose the underlying operation.

## Commercial control plane

- product_editions and edition_versions
- entitlement_definitions and entitlement_grants
- usage_ledger and cost_ledger
- billing_customers, subscriptions, invoices, payments and billing_events
- tenant_budgets and platform_budget_controls
- feature_flags and rollout_assignments

Customer-visible units are projects, chapter reviews, exports, seats and retention. Provider tokens, conversion seconds, storage and egress remain internal cost measures.

## Reliability control plane

- release_records and deployment_records
- service_components and service_incidents
- slo_definitions and sli_measurements
- recovery_policies, backup_records and restore_drills
- maintenance_runs and job leases
- incident records and post-incident actions

## Security and privacy control plane

- revocable application sessions and sensitive-action reauthentication
- privacy-notice and consent versions
- processing-purpose and data-inventory records
- subprocessor registry
- policy-driven retention and deletion jobs
- security-requirement evidence mapped to a declared ASVS version and level
- vulnerability and breach workflows without unsupported compliance claims

## Acceptance demonstration

A signed billing event grants an institutional edition and entitlements; users operate within quotas; one AI provider opens its circuit while editing and exports remain healthy; a failed PDF lease is retried by another worker; a former staff member loses every server session; data export and deletion lifecycle requests are processed honestly; a restore drill reproduces a sealed submission checksum; support retries a failed export using metadata only; the status page reports each component independently; and the audit trail ties billing, document, AI, approval, release and recovery evidence together.

## Explicit exclusions

No Kubernetes, multi-region active-active system, twenty-service decomposition, unlimited AI plan, national university integration, custom payment gateway, autonomous grading, proprietary plagiarism database or unearned SOC 2/ISO/ASVS compliance claim is introduced in this phase.
