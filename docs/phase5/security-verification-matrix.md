# Phase 5 Security Verification Matrix

This matrix uses OWASP ASVS 5.0 as a requirements reference. It is implementation evidence, not a claim of certification or complete ASVS conformance. A qualified independent assessment is still required before any external compliance statement.

| Area | Robofox requirement | Implementation evidence | Automated evidence | Manual evidence / owner |
|---|---|---|---|---|
| Identity | Authentication establishes identity but never grants institution privilege by itself. | `app/api/auth.py`, Phase 4 verified memberships | Auth and tenant-isolation tests | Review domain/invitation workflow — Security owner |
| Sessions | Paid production sessions are server-side, idle/absolute expiring and revocable. | `app/commercial/sessions.py`, `application_sessions` | Phase 5 session API tests | Verify cookie flags and device revocation — Security owner |
| Reauthentication | Billing, policy, feature rollout, recovery and member-session revocation require recent reauthentication. | Commercial APIs and `require_recent_reauthentication` | Phase 5 API tests | Exercise expired reauthentication window — Security owner |
| Authorization | Capabilities are resolved server-side; cross-tenant failures remain opaque. | `app/collaboration/capabilities.py` | Phase 4/5 adversarial tests | Review every new endpoint before release — API owner |
| Tenant isolation | Billing customers/events, projects, memberships and operations remain institution-bound. | Billing tenant binding; institution capability checks | `test_phase5_tenant_isolation.py` | Independent penetration test — Security owner |
| File uploads | Upload size/type/ZIP controls and a fail-closed malware scan run before DOCX parsing. | `app/ingest/preflight.py`, `app/services/malware_service.py`, release ClamAV service | Phase 1 and release-candidate upload tests | Verify ClamAV signature updates, network isolation and EICAR rejection in staging — Operations owner |
| Stored content | Thesis text is not inserted into operational logs, status records or support diagnostics. | Journey middleware and support bundle | Support privacy tests | Log sample inspection — Privacy owner |
| AI data minimisation | AI receives bounded scope and relevant evidence, not an automatic whole-thesis dump. | Phase 3 context compiler | Phase 3 context tests | Provider request sampling without content retention — AI owner |
| AI availability | Provider failure degrades AI only; editing/export remain healthy. | Provider circuits and component health | Phase 5 acceptance test | Provider outage exercise — Reliability owner |
| API abuse | Backend entitlements, monthly quotas, worker deadlines and concurrency limits protect expensive operations. | Commercial guard, entitlement and capacity services | Phase 5 quota tests | Rate-limit/WAF configuration review — Operations owner |
| Billing integrity | Webhooks are signed, idempotent, replayable, order-aware and tenant-bound. | `app/commercial/billing.py` | Billing and tenant-isolation tests | Reconciliation drill — Finance/Operations owner |
| Cryptography | Signing and webhook secrets are environment/secret-store supplied; raw secrets are not persisted. | Settings validation and provider credential references | Secret-pattern CI | Rotation exercise — Security owner |
| Logging | Request/trace/release IDs are recorded without bodies, query strings, emails or thesis content. | `app/commercial/observability.py` | Unit privacy checks | Production log review — Privacy owner |
| Error handling | User-safe errors do not expose stack traces, scanner details or provider credentials. | Central exception handlers | Regression suite | Staging fault injection — Reliability owner |
| Dependencies | Dependency and static security scans run on PRs and weekly with retained diagnostics. | `phase5-security.yml` | pip-audit and Bandit | Triage evidence and exception expiry — Security owner |
| Secrets | Production refuses placeholder secrets or local storage; AI credentials use `env:`/`file:` references. | Settings/model validation and environment verifier | Security workflow | Secret-manager IAM review — Operations owner |
| Recovery | Durable backups require encryption; restore passes only on checksum match. | Recovery models/services/runbook | Recovery and acceptance tests | Scheduled isolated restore drill — Reliability owner |
| Deletion | Deletion is staged, auditable and honest about backup expiry; sealed custody requires authorization. | Privacy lifecycle service | Privacy and tenant tests | R2/database erasure evidence — Privacy owner |
| Support access | Support is time-limited, capability-bound and metadata-only by default. | Phase 4 grants, Phase 5 support console | Support privacy tests | Quarterly support-access review — Support owner |
| Release integrity | Deployments require an exact validated main SHA, immutable image, migration validation, canary and smoke checks. | `main-release-candidate.yml`, durable attestation, `phase5-release.yml` | RC and release workflows | Protected environment approval evidence — Operations owner |

## Verification policy

Each evidence record must have an owner, last verification date and expiration/review date. Exceptions must include business justification, compensating control and expiry. “Implemented” is not equivalent to “independently verified.”

## Required external work before institutional security claims

- Independent tenant-isolation and business-logic penetration test
- Review of production identity/session configuration
- Review of Cloudflare, PostgreSQL, R2 and ClamAV IAM/network boundaries
- Staging EICAR and scanner-outage exercise
- Privacy/legal review of notices, retention, subprocessors and cross-border processing
- Incident tabletop and restore drill with retained evidence
