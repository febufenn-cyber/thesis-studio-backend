"""Claim–citation alignment (docs/LLD_MISSING_FEATURES.md MF2).

Advisory, opt-in, probabilistic: does the cited source span actually support the
manuscript claim? Never gates, never sets Quote.verified, never emits 'verified'.
With no backend configured (default), every claim resolves to 'unverifiable' —
absence of evidence is never evidence of support.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from app.core.config import get_settings

AlignmentStatus = Literal["entailed", "contradicted", "unsupported", "unverifiable"]

__all__ = [
    "AlignmentResult",
    "ClaimAligner",
    "NoopAligner",
    "get_claim_aligner",
]


@dataclass(frozen=True)
class AlignmentResult:
    status: AlignmentStatus
    score: float | None
    method: str  # "none" | "nli:<model>" | "llm:<model>"
    rationale: str = ""


@runtime_checkable
class ClaimAligner(Protocol):
    async def align(self, premise: str, hypothesis: str) -> AlignmentResult: ...


class NoopAligner:
    """Default aligner: no backend, always unverifiable, fail-closed."""

    async def align(self, premise: str, hypothesis: str) -> AlignmentResult:
        return AlignmentResult(status="unverifiable", score=None, method="none")


def get_claim_aligner() -> ClaimAligner:
    """Return the configured aligner, or NoopAligner when disabled/unavailable.

    An 'llm'/'nli' backend would be wired here behind the same Protocol; until a
    calibrated backend ships, we return NoopAligner so nothing is ever asserted
    as entailed without real evidence.
    """
    backend = getattr(get_settings(), "CLAIM_ALIGNMENT_BACKEND", "off")
    if backend == "off":
        return NoopAligner()
    # No live backend is shipped yet; fail closed rather than fabricate support.
    return NoopAligner()
