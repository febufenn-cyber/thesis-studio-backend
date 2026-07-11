# Release Candidate Hardening

This sprint converts the merged Phase 1–5 codebase into a reproducible release candidate. It does not claim that production infrastructure, legal review, institutional approval, or external security testing has already happened.

## Release-candidate promise

A release candidate is acceptable only when the exact `main` commit:

1. compiles and imports;
2. passes every Phase 1–5 regression and acceptance test;
3. completes an Alembic upgrade/downgrade/upgrade round trip;
4. passes dependency, static-security and secret-pattern gates;
5. builds the immutable production image;
6. passes environment validation and smoke tests in staging;
7. records the validated SHA, test totals and evidence links in a durable attestation;
8. remains undeployable to production without protected-environment approval and real backup evidence.

## Work delivered by this sprint

- exact-`main` release-candidate workflow and durable attestation;
- current Phase 1–5 README and operating documentation;
- staging deployment/readiness checklist;
- real-manuscript pilot checklist and institution-profile sign-off record;
- backup/restore and incident-exercise evidence templates;
- production configuration validation for external PostgreSQL, R2, email, billing, AI provider, sessions and malware scanning;
- release smoke tests that verify application, worker, storage, database and component status independently;
- launch-blocker issue templates and release decision record.

## External work this sprint cannot manufacture

- production credentials and infrastructure;
- accountant-approved GST/tax treatment;
- lawyer-approved privacy, DPA and contract language;
- an independent penetration test;
- institution-approved formatting exemplars;
- observed uptime history;
- real backup and restore evidence;
- real billing-provider and AI-provider accounts;
- user acceptance by students, supervisors and operators.

Those items remain explicit release gates and must be evidenced before broad production launch.
