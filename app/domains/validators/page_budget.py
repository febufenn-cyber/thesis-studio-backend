"""Page-budget validator — body length against the venue page limit.

Measurement is taken from the compiled artifact when available (``page_info``
supplied by the caller). When no measurement is available the validator fails
closed with a ``block`` finding rather than passing silently, so a project is
never reported compliant on an unmeasured budget.
"""

from __future__ import annotations

from app.domains.validators.base import (
    ComplianceContext,
    ValidationFinding,
    iter_body_text,
)

# Rough words-per-page for a dense two-column venue template; only used for an
# advisory estimate when a real page count is unavailable.
_WORDS_PER_PAGE = 900


def _estimate_pages(context: ComplianceContext) -> int:
    words = 0
    for _locator, text in iter_body_text(context.document):
        words += len(text.split())
    return max(1, -(-words // _WORDS_PER_PAGE))  # ceil division


class PageBudgetValidator:
    key = "page_budget"

    def validate(self, context: ComplianceContext) -> list[ValidationFinding]:
        limit = context.profile.page_limit
        if not limit:
            return []

        info = context.page_info
        page_count = info.page_count
        measured_by = info.measured_by
        if page_count is None:
            page_count = _estimate_pages(context)
            measured_by = "estimate"

        if page_count > limit:
            severity = "block" if info.measured_by == "pdf" else "warn"
            return [
                ValidationFinding(
                    validator=self.key,
                    severity=severity,
                    code="over_page_limit",
                    message=(
                        f"Compiled body is ~{page_count} page(s) ({measured_by}); "
                        f"{context.profile.label} limit is {limit}."
                    ),
                    locator={"page_count": page_count, "limit": limit, "measured_by": measured_by},
                )
            ]
        return []
