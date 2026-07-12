# Adversarial Test Evidence

Date: 2026-07-12 · Commit `7397fdc` · All cited tests passed in the local
revalidation run recorded in
`docs/release/evidence/MAIN_VALIDATION_7397fdcc008465ce6752e749960f3251059caca8.md`
(173 passed / 0 failed / 0 errors / 0 skipped).

| Required adversarial scenario | Repository test(s) | Status |
|---|---|---|
| Cross-tenant project access | `tests/test_phase5_tenant_isolation.py` (suite), `tests/test_phase4_api.py` cross-tenant cases | passed |
| Metadata-only administration | `tests/test_phase4_operations.py` metadata-only scope cases | passed |
| Private AI history hidden | `tests/test_phase4_acceptance.py` AI-history access flag cases | passed |
| Revoked membership | `tests/test_phase4_evidence.py`, `tests/test_phase5_api.py` revocation cases | passed |
| Invitation replay | `tests/test_phase4_api.py` invitation token (hash, single-use) cases | passed |
| Billing-event tenant crossover | institution-scoped `billing.manage` capability enforcement + `tests/test_phase5_tenant_isolation.py`; webhook idempotency `test_signed_billing_event_is_idempotent_and_provisions_access` | passed |
| Sealed-submission deletion | `tests/test_phase5_tenant_isolation.py` sealed-deletion case; ORM guard `tests/test_phase4_sealed_guard.py` | passed |
| Malformed uploads | `tests/test_phase1_unit.py` preflight/`inspect_docx` malformed-package cases; `tests/test_release_candidate_hardening.py` clamd fail-closed | passed |
| Prompt injection | `tests/test_phase3_evals.py` + live `scripts/run_phase3_evals.py` (2026-07-12): cases `prompt_injection_treated_as_data`, `quote_text_smuggling`, `fabricated_direct_quote`, `ai_detection_evasion` — expectation match 10/10, unsafe acceptance 0.0 | passed |
| Session revocation | `tests/test_phase5_api.py::test_user_can_revoke_all_device_sessions`, reauthentication-window case `test_admin_can_grant_entitlement_after_recent_reauthentication` | passed |
| External-review token manipulation | `tests/test_phase4_acceptance.py` external reviewer cases (expiry, recipient binding, hash-at-rest lookup in `app/api/external_downloads.py`) | passed |

Scope note: these are repository-level adversarial tests executed in a local
environment. They do not substitute for an independent penetration test
(`docs/security/PENTEST_SCOPE.md`) or the manual items in
`EXTERNAL_REVIEW_REQUIRED.md`.
