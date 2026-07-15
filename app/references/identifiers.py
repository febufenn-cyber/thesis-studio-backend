"""Detect and normalize bibliographic identifiers from arbitrary query text.

Classifies a query into one of ``doi | arxiv | isbn | freetext`` and returns a
normalized value. Free-text collapses to a stable sha256 digest so it can key
the resolution cache without storing the raw string.
"""

from __future__ import annotations

import hashlib
import re

__all__ = ["detect_identifier", "normalize_freetext"]

# DOI: 10.<registrant>/<suffix>. Suffix is permissive but stops at whitespace.
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", re.IGNORECASE)

# arXiv new style (1501.00001, optional version) and legacy (math.GT/0309136).
_ARXIV_NEW_RE = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b")
_ARXIV_OLD_RE = re.compile(r"\b([a-z-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b")
_ARXIV_PREFIX_RE = re.compile(r"arxiv\s*[:/]?\s*", re.IGNORECASE)


def normalize_freetext(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for the cache key."""
    lowered = text.lower()
    stripped = re.sub(r"[^\w\s]", " ", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def _clean_isbn(text: str) -> str | None:
    digits = re.sub(r"[^0-9Xx]", "", text)
    if len(digits) == 10 or len(digits) == 13:
        return digits.upper()
    return None


def detect_identifier(text: str) -> tuple[str, str]:
    """Return ``(kind, value)`` for a query string.

    ``kind`` is one of ``doi | arxiv | isbn | freetext``. For ``freetext`` the
    value is a sha256 hex digest of the normalized query, not the raw text.
    """
    candidate = text.strip()

    # arXiv, including an explicit "arXiv:" prefix.
    if _ARXIV_PREFIX_RE.search(candidate):
        rest = _ARXIV_PREFIX_RE.sub("", candidate).strip()
        m = _ARXIV_NEW_RE.search(rest) or _ARXIV_OLD_RE.search(rest)
        if m:
            return "arxiv", m.group(1)
    m = _ARXIV_NEW_RE.fullmatch(candidate) or _ARXIV_OLD_RE.fullmatch(candidate)
    if m:
        return "arxiv", m.group(1)

    # DOI anywhere in the string (also matches a doi.org URL).
    m = _DOI_RE.search(candidate)
    if m:
        doi = m.group(1).rstrip(".").rstrip("/")
        return "doi", doi

    # ISBN only when the query looks ISBN-ish (avoid matching stray digit runs
    # inside a free-text citation).
    if re.search(r"isbn", candidate, re.IGNORECASE) or re.fullmatch(
        r"[0-9][0-9\-\s]{8,20}[0-9Xx]", candidate
    ):
        isbn = _clean_isbn(candidate)
        if isbn:
            return "isbn", isbn

    return "freetext", hashlib.sha256(normalize_freetext(candidate).encode()).hexdigest()
