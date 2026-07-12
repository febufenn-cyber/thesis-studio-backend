# Institution Profile Sign-off — mla_strict (v1)

Instantiates `docs/release/INSTITUTION_PROFILE_SIGNOFF.md`.
**Status: draft — institution certification BLOCKED** (no official
institutional guide on record and no authorised approver; see
`docs/release/EXTERNAL_REVIEW_REQUIRED.md` item 10). Nothing here claims
institutional approval.

## Identity

- Institution profile: `mla_strict` · Version: `mla_strict:v1`
- Label: MLA 9 strict
- Official source guide/exemplar: **not on record** (blocker)
- Approver: **none yet** (blocker)

## Golden artifacts (generated 2026-07-12, real)

- Generator: `scripts/generate_profile_golden.py` at commit `81c9b6ad841bfdc427565099df9de0ca617e3c33`
- Golden canonical fixture SHA-256: `65e6df342adbc07b183e549a9e5bb34d1499a73ed13f32fca9df6e55105563c4`
- Golden DOCX SHA-256: `ca4dd05b5a18821bbf6a8166e24c3a4a1659e66a018d4bedf54d07b25846dc1c`
- Golden DOCX content SHA-256 (zip-stable): `f96cd60cac094da5944c2d7ac7a13896005e9bdf82d60eb11a9bc97546644234`
- PDF: blocked (LibreOffice not installed)
- python-docx: 1.1.2
- Fingerprint (margins, fonts, spacing, pagination): `var/profile-goldens/mla_strict/v1/fingerprint.json` (untracked golden store)

## Verified rules

The 17-point checklist in the template remains **unchecked** pending the
official guide. Deterministic comparison tooling is ready:
`scripts/compare_profile_rules.py --profile mla_strict --rules <transcribed-rules.json>`
(starter example: `docs/release/profile-rules/MCC_MA_ENGLISH.example.json`,
which is explicitly NOT institutional evidence).

## Decision

- Status: `draft` · Institution approval evidence: none
- Robofox reviewer: pending
