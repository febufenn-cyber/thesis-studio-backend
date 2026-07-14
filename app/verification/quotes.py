"""Verbatim quote matching and locator verification (stdlib difflib).

Advisory: produces a status + score, never sets ``Quote.verified``. Exact
substring match after normalization is ``verified``; close-but-not-exact is
``drift``; unrelated is ``not_found``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from app.verification.extractors.base import ExtractedDoc
from app.verification.normalize import normalize

VERBATIM_THRESHOLD = 0.97
DRIFT_THRESHOLD = 0.85

VerbatimStatus = Literal["verified", "drift", "not_found"]


@dataclass(frozen=True)
class VerbatimResult:
    status: VerbatimStatus
    score: float
    matched_locator: str | None
    snippet: str
    method: str = "difflib.ratio"


@dataclass(frozen=True)
class QuoteFinding:
    rule: str
    severity: Literal["warn", "info"]
    detail: dict = field(default_factory=dict)


def _best_window(needle: str, haystack: str) -> tuple[float, str]:
    """Best similarity of ``needle`` against any equal-length window of haystack."""
    if not needle or not haystack:
        return 0.0, ""
    if needle in haystack:
        idx = haystack.index(needle)
        return 1.0, haystack[idx : idx + len(needle)]
    length = len(needle)
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(needle)
    best_score = 0.0
    best_snip = ""
    step = max(1, length // 8)
    limit = max(1, len(haystack) - length + 1)
    for start in range(0, limit, step):
        window = haystack[start : start + length]
        matcher.set_seq1(window)
        score = matcher.ratio()
        if score > best_score:
            best_score = score
            best_snip = window
            if score >= 0.999:
                break
    return best_score, best_snip


def find_best_span(needle: str, haystack: str) -> VerbatimResult:
    """Locate the best match of a quote within source text, classified by score."""
    n = normalize(needle)
    h = normalize(haystack)
    score, snippet = _best_window(n, h)
    if score >= VERBATIM_THRESHOLD:
        status: VerbatimStatus = "verified"
    elif score >= DRIFT_THRESHOLD:
        status = "drift"
    else:
        status = "not_found"
    return VerbatimResult(status=status, score=round(score, 4), matched_locator=None, snippet=snippet)


def _normalize_locator(locator: str) -> str:
    return re.sub(r"^(pp?\.?|pages?)\s*", "", locator.strip(), flags=re.IGNORECASE).strip()


def verify_against_doc(quote_text: str, cited_locator: str, doc: ExtractedDoc) -> tuple[VerbatimResult, list[QuoteFinding]]:
    """Verify a quote against an extracted document; return result + findings."""
    n = normalize(quote_text)

    # Per-page best match, so we can report where the quote actually appears.
    best_page_score = 0.0
    best_locator: str | None = None
    best_snippet = ""
    for page in doc.pages:
        score, snippet = _best_window(n, normalize(page.text))
        if score > best_page_score:
            best_page_score = score
            best_locator = page.locator
            best_snippet = snippet

    whole = find_best_span(quote_text, doc.full_text)
    # Prefer the per-page score when it is at least as good (it carries a locator).
    if best_page_score >= whole.score:
        score = best_page_score
        snippet = best_snippet
        locator = best_locator
    else:
        score = whole.score
        snippet = whole.snippet
        locator = None

    if score >= VERBATIM_THRESHOLD:
        status: VerbatimStatus = "verified"
    elif score >= DRIFT_THRESHOLD:
        status = "drift"
    else:
        status = "not_found"

    result = VerbatimResult(
        status=status, score=round(score, 4), matched_locator=locator, snippet=snippet
    )

    findings: list[QuoteFinding] = []
    if status == "drift":
        findings.append(QuoteFinding("quote_verbatim_drift", "warn", {"score": result.score}))
    elif status == "not_found":
        findings.append(QuoteFinding("quote_not_found_in_source", "warn", {"score": result.score}))

    if status != "not_found" and cited_locator.strip() and locator:
        if _normalize_locator(locator) != _normalize_locator(cited_locator):
            findings.append(
                QuoteFinding(
                    "quote_locator_mismatch",
                    "info",
                    {"cited": cited_locator, "matched": locator},
                )
            )
    return result, findings
