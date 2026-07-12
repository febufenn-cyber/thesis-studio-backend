# Blocker: Billing Sandbox Integration (post-staging)

Status: **deferred by design** (owner decision 2026-07-12). Staging runs
`BILLING_PROVIDER=manual`; entitlement grants, quotas, grace behavior and
institutional access are validated without processing payments. No real
charging is configured anywhere.

## Scope when unblocked (separate PR after staging is healthy)

1. Owner selects a provider (Razorpay or Stripe are the realistic candidates
   for INR institutional + individual plans) and creates a **sandbox/test**
   account only.
2. Set `BILLING_WEBHOOK_SECRET` per environment; point the provider's sandbox
   webhook at `POST /billing/webhooks/<provider>` on staging.
3. Exercise against the sandbox, retaining evidence per case: signed webhook
   verification, replay rejection, idempotent redelivery, out-of-order event
   sequences, and the full state walk trial → active → grace → cancelled →
   refund.
4. Tenant isolation: sandbox events for institution A must never touch
   institution B (extend `tests/test_phase5_tenant_isolation.py` fixtures with
   provider-shaped payloads).
5. Close the reconciliation gap recorded in
   `docs/release/evidence/PROVIDER_BILLING.md`: a reconciliation export
   (entitlement grants + billing events per institution per period) does not
   exist yet and is required before the first real invoice.
6. No production keys until legal/GST review items in
   `docs/release/EXTERNAL_REVIEW_REQUIRED.md` close.

Owner: Febin · Blocking: provider selection + healthy staging.
