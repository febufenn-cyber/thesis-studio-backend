# Blocker: Commercial AI Provider Canary (post-staging)

Status: **deferred by design** (owner decision 2026-07-12). The first staging
acceptance runs with `AI_GLOBAL_ENABLED=false`; every non-AI path must pass
before this work starts. The shared Claude CLI/OAuth session is prohibited as
a staging or commercial dependency.

## Scope of the canary change (separate PR when unblocked)

1. Owner obtains a commercial credential (Anthropic API account or
   institution-supplied gateway).
2. Register a governed provider row (`ai_providers`): adapter `http_json`,
   endpoint via `AI_PROVIDER_<SLUG>_ENDPOINT`, secret via `env:`/`file:`
   reference — never in DB, never in the repo.
3. Configure task routing, per-provider concurrency, spend/entitlement caps;
   verify circuit breaker (threshold 5, cooldown 300s) against a forced
   failure.
4. Record the provider's data-retention terms in
   `docs/release/evidence/PROVIDER_AI.md` (currently marked blocked).
5. Staging exercises: grounded proposal flow, prompt-injection eval corpus
   against the live provider, provider-down drill (app stays ready, AI
   degrades), spend-cap hit behavior.
6. Only then: flip `AI_GLOBAL_ENABLED=true` on staging, re-run the AI slice of
   UAT, and record evidence before any production consideration.

Owner: Febin · Blocking: commercial credential + passed non-AI staging acceptance.
