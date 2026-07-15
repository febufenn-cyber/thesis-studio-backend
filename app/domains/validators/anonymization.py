"""Double-blind anonymization lint.

Flags identity leaks that break double-blind review: de-anonymizing links/emails
(block), acknowledgement/funding disclosures (block/warn), and first-person
self-citation phrasing (warn). Heuristic — unambiguous leaks block, ambiguous
signals warn — so it is useful without being brittle.
"""

from __future__ import annotations

import re

from app.domains.validators.base import (
    ComplianceContext,
    ValidationFinding,
    iter_body_text,
)

_ANON_HOSTS = ("anonymous.4open.science", "osf.io/anonymous")
_LINK_RE = re.compile(r"\b(?:https?://|www\.)\S+|github\.com/\S+|gitlab\.com/\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_ORCID_RE = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")
_FUNDING_RE = re.compile(
    r"\b(funded by|grant no\.?|grant number|supported by|we thank|acknowledge the support)\b",
    re.IGNORECASE,
)
_SELF_CITE_RE = re.compile(r"\b(our|we|my)\s+(previous|prior|earlier)\s+work\b", re.IGNORECASE)


def _is_anonymized(url: str) -> bool:
    return any(host in url.lower() for host in _ANON_HOSTS)


class DoubleBlindValidator:
    key = "double_blind"

    def validate(self, context: ComplianceContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []

        # Acknowledgement front-matter must not be present for a blind submission.
        for entry in context.document.front_matter:
            if entry.kind == "acknowledgement":
                findings.append(
                    ValidationFinding(
                        self.key, "block", "acknowledgement_present",
                        "An acknowledgement section can de-anonymize a double-blind submission.",
                        {"front_matter": entry.kind},
                    )
                )

        for locator, text in iter_body_text(context.document):
            for match in _LINK_RE.findall(text):
                if not _is_anonymized(match):
                    findings.append(
                        ValidationFinding(
                            self.key, "block", "deanonymizing_link",
                            f"Non-anonymized link may reveal author identity: {match}",
                            {**locator, "match": match},
                        )
                    )
            if _EMAIL_RE.search(text):
                findings.append(
                    ValidationFinding(
                        self.key, "block", "email_present",
                        "An email address can de-anonymize a double-blind submission.",
                        locator,
                    )
                )
            if _ORCID_RE.search(text):
                findings.append(
                    ValidationFinding(
                        self.key, "block", "orcid_present",
                        "An ORCID can de-anonymize a double-blind submission.", locator,
                    )
                )
            if _FUNDING_RE.search(text):
                findings.append(
                    ValidationFinding(
                        self.key, "warn", "funding_or_thanks",
                        "Funding/acknowledgement wording may reveal identity; move to camera-ready.",
                        locator,
                    )
                )
            if _SELF_CITE_RE.search(text):
                findings.append(
                    ValidationFinding(
                        self.key, "warn", "self_citation_phrasing",
                        "First-person prior-work phrasing can leak identity; cite in third person.",
                        locator,
                    )
                )
        return findings
