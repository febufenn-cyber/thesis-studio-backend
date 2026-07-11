# Robofox Thesis Studio — Data Map

This operational data map supports accurate privacy notices, retention configuration and deletion workflows. Contract terms and legal obligations must be reviewed for each institution.

| Data class | Purpose | Data subject / owner | Primary storage | Typical retention authority | Shared with | Active-system deletion path |
|---|---|---|---|---|---|---|
| Email and identity provider subject | Authentication and account recovery | User | PostgreSQL | Account/contract lifecycle | Email/identity provider | Account lifecycle anonymises identity and revokes sessions |
| Institution and department membership | Authorization and academic workflow | Institution and member | PostgreSQL | Contract plus audit requirements | Institution administrators | Membership revocation; minimal historical actor record retained where required |
| Device session metadata | Security and revocation | User | PostgreSQL | Session lifetime plus short audit period | None by default | Revoke session; scheduled retention cleanup |
| Original manuscript revision | Processing and recovery | Student, subject to institution contract | R2 durable prefix + PostgreSQL reference | Institution/contract policy | AI provider only for explicitly required bounded tasks | Project lifecycle deletes active object after grace/authorization checks |
| Canonical document and snapshots | Editing, review and reproducibility | Student author; institution custody as agreed | PostgreSQL | Project/submission policy | Assigned collaborators | Project lifecycle; sealed package may require institution authorization |
| Sources and quotations | Citation traceability | Student/project | PostgreSQL | Project/submission policy | Assigned reviewers with source permission | Project lifecycle |
| Comments, suggestions and approvals | Academic review and audit | Participants/institution | PostgreSQL | Workflow/submission policy | Authorized project members | Project lifecycle subject to sealed/audit obligations |
| Private AI conversation | Academic assistance | User | PostgreSQL and configured AI provider | Configurable AI-chat retention | AI provider for bounded request | Retention sweep or account lifecycle |
| AI context manifest and provenance | Accountability and reproducibility | Project/institution | PostgreSQL | Project/submission policy | Authorized audit roles | Project lifecycle subject to sealed provenance obligations |
| AI provider usage and cost metadata | Capacity and unit economics | Customer account | PostgreSQL | Finance/operations policy | Provider and finance operations | Contract/account lifecycle; content is not stored in cost ledger |
| Preview/PDF temporary artifacts | User preview and conversion | Project | R2 rebuildable prefixes | Short configured lifecycle | LibreOffice worker; download recipient | Retention sweep / object lifecycle |
| Draft exports | User delivery | Project | R2 export prefix | Configurable | Authorized downloader | Project lifecycle / export retention |
| Sealed submission package | Institutional submission and audit | Student/institution under contract | PostgreSQL + R2 durable prefix | Contract/institution policy | Approved examiner/download recipient | Withdrawal/supersession; deletion requires applicable authorization |
| Billing customer/subscription/invoice/payment | Commercial administration | Buyer/customer | PostgreSQL + billing provider | Tax/accounting/contract policy | Billing provider, accountant as approved | Financial retention policy; entitlement access can be revoked immediately |
| Billing webhook payload | Auditable subscription lifecycle | Customer | PostgreSQL | Billing event retention policy | Billing provider | Scheduled finance retention; payload excludes payment-card details |
| Support action and diagnostic metadata | Troubleshooting and accountability | Customer/project | PostgreSQL | Support/audit policy | Authorized support | Scheduled retention; thesis content excluded by default |
| Request/trace logs | Reliability and security | Platform/customer metadata | Logging platform | Short operational/security policy | Authorized operations/security staff | Log retention expiry |
| Backup copies | Recovery | Mirrors source data classes | Encrypted off-host backup | Backup expiry schedule | Backup provider | Active deletion followed by documented backup expiry |

## Data-minimisation rules

1. Do not log request bodies, query strings, thesis prose, quotations, AI prompts or full email addresses.
2. AI requests include only selected scope, required summaries/evidence and applicable policy.
3. Support diagnostics expose versions, checksums, states and object presence—not manuscript content.
4. Billing and analytics operate on identifiers, quantities and outcomes, not academic content.
5. External-review access is bound to recipient, sealed version, expiry and explicit download permission.

## Deletion terminology

The product must distinguish:

- access removed
- archived
- grace period
- active database deleted/anonymised
- active object storage deleted
- backup expiry scheduled
- deletion blocked by sealed custody or legal/administrative hold

“Permanently deleted” must not be shown while encrypted backups remain within their documented expiry period.
