# Institution Profile Sign-off — tn_university (compat-unverified-v1)

Instantiates `docs/release/INSTITUTION_PROFILE_SIGNOFF.md`.
**Status: draft — institution certification BLOCKED** (no official
institutional guide on record and no authorised approver; see
`docs/release/EXTERNAL_REVIEW_REQUIRED.md` item 10). Nothing here claims
institutional approval.

## Identity

- Institution profile: `tn_university` · Version: `tn_university:compat-unverified-v1`
- Label: Generic Tamil Nadu · spacing must be confirmed
- Official source guide/exemplar: **not on record** (blocker)
- Approver: **none yet** (blocker)

## Golden artifacts (generated 2026-07-12, real)

- Generator: `scripts/generate_profile_golden.py` at commit `81c9b6ad841bfdc427565099df9de0ca617e3c33`
- Golden canonical fixture SHA-256: `65e6df342adbc07b183e549a9e5bb34d1499a73ed13f32fca9df6e55105563c4`
- Golden DOCX SHA-256: `5e20c16724a3ef81bfa4b36a18deb6584a8b1d7ae1d42328ea8ced76462c20dc`
- Golden DOCX content SHA-256 (zip-stable): `c59c9ffbc0873423684f2c3dacccb2996c4f57f3012a7f14ef1730cabaf2956a`
- PDF: blocked (LibreOffice not installed)
- python-docx: 1.1.2
- Fingerprint (margins, fonts, spacing, pagination): `var/profile-goldens/tn_university/compat-unverified-v1/fingerprint.json` (untracked golden store)

## Verified rules

The 17-point checklist in the template remains **unchecked** pending the
official guide. Deterministic comparison tooling is ready:
`scripts/compare_profile_rules.py --profile tn_university --rules <transcribed-rules.json>`
(starter example: `docs/release/profile-rules/MCC_MA_ENGLISH.example.json`,
which is explicitly NOT institutional evidence).

## Decision

- Status: `draft` · Institution approval evidence: none
- Robofox reviewer: pending
