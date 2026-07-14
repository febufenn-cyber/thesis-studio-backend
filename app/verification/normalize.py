"""Text normalization for verbatim quote matching.

Folds the differences that legitimately vary between a quotation and its source
(smart quotes, dashes, ligatures, whitespace, case) so that a true verbatim
quote matches, while genuine wording differences still register as drift.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["normalize"]

_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "‒": "-", "―": "-", "−": "-",
    "…": "...",
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    " ": " ",
}

_TRANSLATION = {ord(k): v for k, v in _FOLD.items()}


def normalize(text: str, *, fold_case: bool = True) -> str:
    """Return a normalized form suitable for verbatim comparison."""
    folded = unicodedata.normalize("NFKC", text).translate(_TRANSLATION)
    # Strip leading/trailing ellipsis elision markers a quoter may add.
    folded = folded.strip().strip(".").strip()
    collapsed = re.sub(r"\s+", " ", folded).strip()
    return collapsed.casefold() if fold_case else collapsed
