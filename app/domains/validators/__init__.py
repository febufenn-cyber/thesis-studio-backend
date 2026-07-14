"""Compliance validators for enforcing DomainProfiles (docs/LLD.md 3.4).

Each validator is a pure function of a ``ComplianceContext`` (canonical document
+ profile + measured page info). ``run_profile`` resolves and runs a profile's
declared validators and returns the combined findings; a ``block`` finding gates
submission, ``warn``/``info`` are advisory.
"""

from __future__ import annotations

from app.domains.validators.anonymization import DoubleBlindValidator
from app.domains.validators.base import (
    ComplianceContext,
    PageInfo,
    ProfileValidator,
    UnknownValidator,
    ValidationFinding,
)
from app.domains.validators.page_budget import PageBudgetValidator
from app.domains.validators.reproducibility import ReproducibilityChecklistValidator

_VALIDATORS: dict[str, ProfileValidator] = {
    v.key: v
    for v in (
        PageBudgetValidator(),
        DoubleBlindValidator(),
        ReproducibilityChecklistValidator(),
    )
}


def get_validator(key: str) -> ProfileValidator:
    try:
        return _VALIDATORS[key]
    except KeyError as exc:
        raise UnknownValidator(key) from exc


def run_profile(context: ComplianceContext) -> list[ValidationFinding]:
    """Run every validator the context's profile declares."""
    findings: list[ValidationFinding] = []
    for key in context.profile.validators:
        findings.extend(get_validator(key).validate(context))
    return findings


__all__ = [
    "ComplianceContext",
    "PageInfo",
    "ProfileValidator",
    "ValidationFinding",
    "UnknownValidator",
    "get_validator",
    "run_profile",
]
