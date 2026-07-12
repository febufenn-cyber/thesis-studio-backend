# Real Manuscript Pilot

Automated fixtures prove code paths. This pilot proves that Robofox handles real academic documents without silent loss.

## Corpus requirements

Use anonymised or synthetic-equivalent documents with permission. The pilot set should include at least:

- 50–200 pages;
- multiple institutions/programmes;
- tables, figures, captions and poetry;
- footnotes/endnotes;
- comments and tracked changes;
- manual and automatic tables of contents;
- multiple works by one author and same-surname authors;
- primary and secondary quotations;
- unusual source types;
- mixed Roman/Arabic numbering;
- malformed or near-limit DOCX packages;
- one post-viva revision.

Never place identifiable student manuscripts in the repository or CI artifacts.

## Per-document evidence

- Pilot ID:
- Consent/permission record:
- Original SHA-256:
- Page count / file size:
- Institution profile and version:
- Upload malware result:
- Preflight object counts:
- Non-empty source text accounted for:
- Unsupported objects reported:
- Chapter-boundary findings:
- Heading findings:
- Citation ambiguities:
- Quotations linked/unlinked:
- Human corrections required:
- Final verifier result:
- DOCX checksum:
- PDF checksum:
- DOCX reopened successfully:
- PDF pagination manually checked:
- Original-vs-final content-loss review:
- Operator sign-off:
- Student/academic reviewer sign-off where permitted:

## Release thresholds

- Zero silently discarded non-empty text.
- Zero unsupported objects omitted from the report.
- Zero fabricated bibliographic fields or quotations.
- Every ambiguous citation requires a human decision.
- Final DOCX and PDF open successfully and match the pinned profile.
- Every discrepancy has a stable issue, resolution or acknowledged exclusion.

A release candidate fails when any pilot discovers silent loss, cross-project leakage, unverifiable final output or an unrecoverable revision.
