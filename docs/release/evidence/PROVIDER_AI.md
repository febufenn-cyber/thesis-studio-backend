# Provider Readiness — AI

Date: 2026-07-12 · Commit `7397fdc` · Environment: local validation + repo inspection

## Validated (real, local)

- **Governed adapter architecture** (`app/ai/provider.py`, `app/ai/adapters.py`,
  `app/commercial/ai_capacity.py`): two adapters — `claude_cli` subprocess with
  tools disabled (`--tools ""`, `--strict-mcp-config`, `--no-session-persistence`,
  600s timeout) and `http_json` gateway with Bearer secret via `env:`/`file:`
  reference (never stored in DB). Routing via `ai_providers`/`ai_provider_health`.
- **Circuit breaker**: opens after `AI_PROVIDER_FAILURE_THRESHOLD=5` failures,
  cooldown `AI_CIRCUIT_COOLDOWN_SECONDS=300`, half-open retry. Application
  readiness is independent of AI health — validated by
  `tests/test_phase5_reliability.py::test_commercial_readiness_survives_provider_and_worker_failure`
  (passed in the 173/0/0/0 run recorded in `MAIN_VALIDATION_7397fdc….md`).
- **Task routing + AI queue**: `ai_run` jobs route to the dedicated `ai` queue
  (`app/services/job_queue.py` `_QUEUE_BY_KIND`).
- **Spend/entitlement caps**: enforced backend-side via entitlement grants —
  `test_scope_specific_entitlement_grant_wins`,
  `test_feature_rollout_prefers_user_over_tenant` (both passed).
- **Kill switch / AI-disabled deterministic mode**: `AI_GLOBAL_EMERGENCY_THROTTLE`
  hard throttle; `AI_GLOBAL_ENABLED=false` is exercised by CI's production
  config safety test (`.github/workflows/phase5-security.yml`) and passed in
  this validation's fail-closed check. Deterministic editing/review/export
  remain available with AI off (`app/ai/capacity.py`).
- **Safety evals (run live 2026-07-12)**: `python scripts/run_phase3_evals.py`
  → rc 0, `cases: 10`, `expectation_match_rate: 1.0`,
  `unsafe_acceptance_rate: 0.0`, `schema_validity_rate: 0.8` (the two
  schema-invalid cases are rejection fixtures and matched expectations).
- **Context minimisation**: prompts assembled from scoped project context in
  `app/ai/` (phase 3 grounded design); no full-manuscript dumps in prompts.

## Blocked (external)

| Item | Why | Unblock |
|---|---|---|
| Commercial or institution-supplied credential | No `AI_PROVIDER_*` endpoint/secret exists in any environment | Create governed provider account; configure `AI_PROVIDER_<SLUG>_ENDPOINT` + secret ref in staging `.env` |
| Provider data-retention policy record | Requires the commercial agreement | Record retention terms in this file once the account exists |
| Live provider health probe from staging | No staging host | See `docs/release/STAGING_BLOCKERS.md` |

## Pilot CLI status

The Claude Code CLI on the v1 Oracle VM (Max-subscription OAuth, verified
2026-07-11 with a live `claude -p` call) is the **pilot** path only.
`PHASE5-COMMERCIAL-OPERATING-CONTRACT.md` forbids it as a commercial
dependency; staging/production must use the governed `http_json` provider or
deploy AI-disabled. Both paths exist and are tested.
