# Release Decision Record

Use one record for each staging promotion or production canary. A green CI run is necessary but not sufficient for a production decision.

## Candidate

- Release SHA:
- Validation attestation: `release-candidates/<sha>.json`
- Container digest:
- Migration head:
- Target: `staging | production-canary | production`
- Decision meeting date:

## Required evidence

- [ ] Exact-main validation and security gates passed.
- [ ] Staging acceptance completed.
- [ ] Real-manuscript pilot thresholds passed.
- [ ] Required institution profiles are signed off.
- [ ] Backup/restore drill passed within internal RPO/RTO targets.
- [ ] Production environment verifier passed.
- [ ] Billing provider sandbox/manual reconciliation passed.
- [ ] Commercial AI provider or AI-disabled release mode approved.
- [ ] Email delivery and bounce handling tested.
- [ ] Tenant-isolation/security review completed.
- [ ] Privacy/terms/DPA wording reviewed by qualified counsel.
- [ ] GST/accounting process reviewed by a qualified accountant.
- [ ] Support and incident ownership assigned.
- [ ] Rollback owner and known-good release identified.
- [ ] Canary institution/user consent recorded.

## Open risk assessment

| Risk | Severity | Evidence/mitigation | Owner | Expiry |
|---|---|---|---|---|
| | | | | |

## Decision

- Decision: `go | conditional go | no-go`
- Scope/tenant percentage:
- Conditions:
- Approved by product:
- Approved by engineering/operations:
- Approved by privacy/security:
- Rollback trigger:
- Observation window:

Do not convert internal objectives into a customer SLA through this document. External commitments require a contract and observed operational history.
