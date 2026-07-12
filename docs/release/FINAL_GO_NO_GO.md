# Final Go / No-Go — Staging and Launch Readiness Mission

Date: 2026-07-12 · Branch: `agent/staging-and-launch-readiness`
Base: main `7397fdcc008465ce6752e749960f3251059caca8` (attested RC `0941ebda78fb7b1b3e522e95b609a7f35e15ba73`)
Completion commit: see PR head (this file's commit).

## Recommendation: **STAGING PILOT ONLY**

The codebase is validated, two real defects found during this mission are
fixed with regression coverage, and every launch-readiness harness exists and
has been executed locally. Nothing here is production evidence: staging
infrastructure does not exist, no real manuscripts have been piloted, no
profile is institution-certified, and the external review gates are open.
Production is **NO-GO** until the items below close. **Production was not
deployed; staging was not deployed (nothing to deploy to).**

## Commits made (this branch, in order)

| Commit | Subphase | Summary |
|---|---|---|
| `e0a7a1a` | A | fix: hermetic production-safety Settings tests |
| `2c84a5e` | A | chore: validate merged release candidate at 7397fdc |
| `d247378` | B | infra: staging blockers with verified-absent inventory |
| `81c9b6a` | F | ops: provider readiness evidence (5 providers) |
| `2d0d7fc` | G | docs: security and privacy external-review package |
| `ed1e301` | A/I | fix: optimistic-concurrency lost-update race (row-lock gate) |
| `27b27a7` | A/D | fix: canonical schema version derived from model constant |
| `09d8fbe` | C | ops: backup and restore drill automation, executed locally |
| `9fca7cb` | D | test: manuscript pilot harness, synthetic corpus executed |
| `ca48980` | E | ops: profile sign-off tooling with generated goldens |
| `92da7d9` | H | test: UAT flows for six roles, 74/0/4/9 locally |
| `64b2cbd` | I | test: local performance benchmark with measured baselines |

## Results by area

**Tests (final re-run at branch HEAD):** `pytest -q` → **174 passed, 0
failed, 0 errors, 0 skipped** (173 baseline + 1 new concurrency regression
test). compileall, app import, 8× `node --check`, bandit (`-r app -x tests
-ll -ii`), secret-pattern scan: all pass. pip-audit (installed clean env): no
known vulnerabilities.

**Migrations:** `head → 0016 → head` round trip on a fresh database; final
`alembic current` = `0018 (head)`; schema version agrees with config, release
identity and the restored drill database.

**Defects found and fixed (both real, both with regression evidence):**
1. Lost-update race — two interleaved same-base-version saves both returned
   200; second commit silently destroyed the first (data-loss class). Fixed
   with `SELECT … FOR UPDATE` version gate; new test fails pre-fix, passes
   post-fix (`ed1e301`).
2. Release identity reported canonical schema `"1"` while every document
   carries `3`. Config now derives from the model constant (`27b27a7`).
3. (A) Production-safety tests were not hermetic to a developer `.env`
   (`e0a7a1a`).

**Security:** 12-document review package under `docs/security/` (diagrams,
STRIDE threat model, data inventory, retention map, subprocessors, logging
redaction, session model, support access, vuln reporting, pen-test scope);
all 11 required adversarial scenarios map to passing repository tests
(`docs/security/ADVERSARIAL_TEST_EVIDENCE.md`). No certification claimed.

**Staging deployment:** **BLOCKED** — zero GitHub environments, zero Actions
secrets, no isolated host/DB/R2/ClamAV (`docs/release/STAGING_BLOCKERS.md`
has the exact commands per blocker). The official workflow was not run;
nothing was deployed anywhere.

**Restore drill:** local drill executed twice, PASS (24/24 integrity checks,
sealed checksums identical, RTO 1.2s/2.6s on toy data, RPO 0). Staging drill
blocked (`RESTORE_DRILL_2026-07-12.md`).

**Manuscript pilot:** synthetic corpus (14 fixtures) executed — 12/12
processed files pass all 7 thresholds; malformed-zip and zip-bomb correctly
rejected by existing guards. **Real institutional manuscripts outstanding.**
Parser findings recorded (equation double-count, tracked-changes text
reported-not-extracted, styled-heading gap) — none are silent-loss class.

**Institution profiles:** golden fixtures + fingerprints generated for all
three profiles; comparison/pinning tooling ready; all three sign-off records
are **draft — certification blocked** on official guides and approvers.

**Providers:** email READY (Resend live, DKIM/SPF/DMARC verified). Billing:
manual mode ready; online sandbox absent. AI: governed adapter + AI-disabled
mode tested; commercial credential absent (pilot CLI must not be commercial).
Storage: R2 unprovisioned. ClamAV: code paths fail closed; live scanner
blocked (`PROVIDER_*.md`).

**UAT:** 87-step driver across six roles run locally — 74 pass, 0 fail, 4
manual (human checklists provided), 9 requires-staging.

**Performance:** local baselines measured (open p95 54ms @5k blocks; save
p95 541ms @5k — scales with document size, ~264 ms/MiB, the capacity
constraint to watch; queue claim 323 jobs/s). SLO compliance **not
assessable locally**; 25/50/100-user load tests blocked.

## Unresolved blockers (owner: Febin unless noted)

1. Staging infrastructure + secrets (11 items, `STAGING_BLOCKERS.md`)
2. Real-manuscript pilot with consent + human reviewers
3. Institution profile certification (guides + authorised approvers)
4. Commercial AI credential or explicit AI-disabled launch decision
5. Billing sandbox or manual-only confirmation; reconciliation export gap
6. External review items 1–15 (`EXTERNAL_REVIEW_REQUIRED.md`: legal, pen
   test, IAM review, live EICAR, tabletop, staging restore drill)
7. Resend paid tier + bounce webhook before cohort-scale email

## Honest scope statement

Every result above is labeled real/synthetic/local/blocked in its evidence
file. A green suite plus local harnesses does not make this production-ready;
it makes it ready to be **proven** on staging. Recommended path: provision
staging per the blockers doc → dispatch `phase5-release.yml` (staging) →
staging restore drill + UAT + load tests → real-manuscript pilot → profile
certification → external reviews → revisit this decision for LIMITED CANARY.
