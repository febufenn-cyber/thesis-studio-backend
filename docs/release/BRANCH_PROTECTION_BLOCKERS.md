# Branch Protection Status and Blockers

Date: 2026-07-12 · Repo: `febufenn-cyber/thesis-studio-backend` (user-owned, public)

## Finding (Subphase A)

The staging provisioning package (`9814c0a`) **was pushed directly to main**
by the repository owner's instruction on 2026-07-12 — no branch protection
existed at the time (verified: zero rulesets, `branches/main/protection` →
404). The release chain still held because the RC workflow validates every
main push and the attestation bot recorded `release-candidates/9814c0a….json`
(`e133f27`, attestation-only). Going forward the intended policy is PR-only.

## What is enforced NOW (verified via API after creation)

| Ruleset | ID | Enforcement | Rules |
|---|---|---|---|
| `main integrity (force-push and deletion block)` | 18827479 | **active** | `non_fast_forward`, `deletion` — applies to everyone including admins; attestation pushes are fast-forward commits and remain unaffected |
| `main pr discipline (activate after attestation bypass fix)` | 18827483 | **disabled (parked)** | `pull_request` (0 approvals) + `required_status_checks` (`validate`, `security`, strict up-to-date) |

Do not treat PR-requirement as active: **it is not** — verified, not assumed.

## Why the PR ruleset is parked, precisely

1. The release-attestation workflow (`main-validation-attestation.yml`)
   pushes its evidence commit directly to main using `GITHUB_TOKEN`
   (`github-actions[bot]`).
2. GitHub **rejects the GitHub Actions integration as a bypass actor on
   user-owned repositories** (422: "Actor GitHub Actions integration must be
   part of the ruleset source or owner organization") — this bypass works
   only in organization-owned repos.
3. `evaluate` (dry-run) enforcement is also unavailable on this plan (422).
4. Activating the PR rule today would therefore break the attestation chain:
   the bot's push would be rejected and no `release-candidates/<sha>.json`
   would be produced — which the release workflow requires.

## Upgrade paths (pick one, then activate)

**Path 1 — move the repo into a GitHub organization** (recommended long-term).
Org-owned repos accept the Actions integration as a bypass actor:

```bash
# after transfer:
gh api -X PUT repos/<ORG>/thesis-studio-backend/rulesets/18827483 \
  -f enforcement=active
gh api -X PUT repos/<ORG>/thesis-studio-backend/rulesets/18827483 \
  --input - <<< '{"bypass_actors":[{"actor_id":15368,"actor_type":"Integration","bypass_mode":"always"}]}'
```

**Path 2 — PR-based attestation (repo-only change, no transfer).** Modify
`main-validation-attestation.yml` to write the evidence file on a bot branch,
open a PR, and enable auto-merge; the RC + security checks run on that PR and
merge it automatically. Then simply:

```bash
gh api -X PUT repos/febufenn-cyber/thesis-studio-backend/rulesets/18827483 \
  -f enforcement=active
```

This changes a locked workflow file and adds ~10 min latency per attestation —
it needs owner approval and its own PR.

**UI equivalent:** Settings → Rules → Rulesets → "main pr discipline" →
Enforcement: Active.

## Owner-lockout check

The owner is not in any bypass list, but as repository admin can edit or
delete rulesets at any time — no lockout is possible. Production deployment
approval is independently enforced by the `production` GitHub environment
(required reviewer + protected branches), unchanged by any of this.
