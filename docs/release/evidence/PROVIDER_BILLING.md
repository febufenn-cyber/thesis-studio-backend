# Provider Readiness — Billing

Date: 2026-07-12 · Commit `7397fdc`

## Selected mode

**Manual institutional invoicing** (`BILLING_PROVIDER=manual`, the repo
default). Institutional manual contracts grant entitlements without an online
subscription, per `PHASE5-COMMERCIAL-OPERATING-CONTRACT.md`. No online payment
provider is selected yet; no sandbox account exists.

## Validated (real, local — all in the 173/0/0/0 suite run)

- **Signed webhook verification**: canonical `t=,v1=` HMAC-SHA256 against
  `BILLING_WEBHOOK_SECRET` with timestamp tolerance window, constant-time
  compare — `tests/test_phase5_unit.py::test_billing_signature_is_timestamped_and_constant_time`.
- **Idempotency + provisioning**:
  `tests/test_phase5_api.py::test_signed_billing_event_is_idempotent_and_provisions_access`
  (same event delivered twice → one provisioning effect).
- **Replay protection**: timestamp tolerance (`BILLING_WEBHOOK_TOLERANCE_SECONDS`)
  plus `store_event`/`replay_event` dedup in `app/commercial/billing.py`.
- **Entitlement precedence / tenant scoping**:
  `test_scope_specific_entitlement_grant_wins`,
  `test_feature_rollout_prefers_user_over_tenant`,
  `test_admin_can_grant_entitlement_after_recent_reauthentication` (admin
  actions require recent reauthentication).
- **Tenant isolation**: billing routes gated by
  `require_institution_capability(..., "billing.manage")`;
  `tests/test_phase5_tenant_isolation.py` passed.
- **No production charges during testing**: trivially satisfied — no payment
  provider credential exists anywhere.

## Blocked / gaps (honest)

| Item | Status |
|---|---|
| Online provider sandbox (signed webhooks end-to-end over HTTP) | Blocked — no provider selected/account. Unblock: choose provider (e.g. Razorpay/Stripe), create sandbox, set `BILLING_WEBHOOK_SECRET` per environment, replay provider fixtures against `POST /billing/webhooks/{provider}` in staging. |
| Out-of-order event sequences; full trial→active→grace→cancelled→refund state walk | Partially covered (idempotency/replay tested); a full lifecycle fixture suite against a sandbox is outstanding. |
| Reconciliation export | No dedicated reconciliation export endpoint found in `app/` — manual-invoicing reconciliation currently relies on entitlement-grant audit rows. Flagged as a pre-commercial-launch gap. |
