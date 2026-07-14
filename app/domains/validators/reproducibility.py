"""Reproducibility-checklist validator.

Turns the venue's reproducibility checklist into a gate: the reproducibility
section must be present and, if the profile expects structured answers, every
item in ``project.meta['reproducibility']`` must be answered.
"""

from __future__ import annotations

from app.domains.validators.base import ComplianceContext, ValidationFinding

_REPRO_SECTIONS = ("reproducibility_checklist", "broader_impacts")


class ReproducibilityChecklistValidator:
    key = "reproducibility"

    def validate(self, context: ComplianceContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        required = {s for s in _REPRO_SECTIONS if s in {sec.name for sec in context.profile.sections}}
        missing = [name for name in required if name not in context.present_sections]
        for name in sorted(missing):
            findings.append(
                ValidationFinding(
                    self.key, "block", "reproducibility_section_missing",
                    f"Required section '{name}' is missing.",
                    {"section": name},
                )
            )

        answers = context.reproducibility_answers or {}
        unanswered = [
            item for item, value in answers.items()
            if not str((value or {}).get("answer", "") if isinstance(value, dict) else value).strip()
        ]
        for item in sorted(unanswered):
            findings.append(
                ValidationFinding(
                    self.key, "block", "reproducibility_incomplete",
                    f"Reproducibility item '{item}' is unanswered.",
                    {"item": item},
                )
            )
        return findings
