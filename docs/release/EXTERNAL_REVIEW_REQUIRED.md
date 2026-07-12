# External Review Required

Date: 2026-07-12 · Commit `7397fdc`

Everything in this file is work the repository **cannot** complete or attest
by itself. No claim of completion is made anywhere in this repo for these
items; the release decision must treat each as an open gate.

## Legal / compliance (needs counsel or qualified professional)

| # | Item | Needed from | Blocking for |
|---|---|---|---|
| 1 | Privacy policy, Terms of Service, DPA templates reviewed by counsel (India DPDP Act posture explicitly assessed) | Lawyer | Any commercial or institutional launch |
| 2 | GST/tax treatment of subscriptions and institutional invoices | Accountant | First invoice |
| 3 | Subprocessor DPAs (Cloudflare, Resend, Anthropic, Oracle) executed and recorded in `docs/security/SUBPROCESSORS.md` | Owner + counsel | Institutional contracts |
| 4 | Safe-harbor wording in `docs/security/VULNERABILITY_REPORTING.md` | Lawyer | Publishing the security page |

## Independent security (needs third party)

| # | Item | Needed from | Blocking for |
|---|---|---|---|
| 5 | Penetration test per `docs/security/PENTEST_SCOPE.md` against a staging deployment | External firm | Production with institutional data |
| 6 | Production identity/session review (cookie flags, session fixation, token entropy) on the deployed stack | External reviewer | Production |
| 7 | Cloud IAM review: Cloudflare account, R2 tokens, OCI credentials, GitHub environment protection | External reviewer or second operator | Production |
| 8 | Staging EICAR + scanner-outage live exercise (retain rejection evidence) | Operator on staging | Production uploads |
| 9 | Incident-response tabletop + staging restore drill executed against real infrastructure | Operator + reviewer | Production |

## Institutional / human approval

| # | Item | Needed from | Blocking for |
|---|---|---|---|
| 10 | Official formatting guides or approved exemplars per institution; written profile approval by an authorised person (template: `docs/release/INSTITUTION_PROFILE_SIGNOFF.md`) | Institution | Calling any profile institution-certified |
| 11 | Real anonymised manuscript pilot with consent records and human reviewer sign-off (harness: `scripts/run_manuscript_pilot.py`) | Students/operators with consent | Pilot thresholds in `REAL_MANUSCRIPT_PILOT.md` |
| 12 | UAT human checklists executed on staging by real role-holders (`docs/release/evidence/UAT_CHECKLISTS.md`) | Pilot users | Staging acceptance decision |

## Commercial accounts

| # | Item | Needed from | Blocking for |
|---|---|---|---|
| 13 | Governed AI provider credential (commercial or institution-supplied) or an explicit AI-disabled launch decision | Owner | AI features in staging/production |
| 14 | Billing provider sandbox + full event-lifecycle exercise, or confirmation of manual-invoicing-only launch | Owner | Paid plans |
| 15 | Resend paid tier (or institutional SMTP) + bounce webhook before cohort-scale email | Owner | Institutional onboarding |

## Explicitly NOT claimed by this repository

ASVS compliance · SOC 2 · ISO 27001 · DPDP compliance · completed penetration
testing · completed legal review · uptime SLA · zero-data-loss guarantee ·
institutional approval. `docs/phase5/security-verification-matrix.md` maps
ASVS 5.0 as a *reference frame only*.
