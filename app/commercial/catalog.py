"""Stable customer-facing entitlement catalog shared by migrations, APIs and tests."""

from __future__ import annotations

from typing import Any


ENTITLEMENT_CATALOG: dict[str, dict[str, Any]] = {
    "project.create": {"value_type": "boolean", "unit": None, "description": "Create thesis projects.", "metered": False, "reset_period": None},
    "project.active_limit": {"value_type": "integer", "unit": "active_projects", "description": "Maximum active projects.", "metered": True, "reset_period": None},
    "manuscript.max_size_mb": {"value_type": "integer", "unit": "megabytes", "description": "Maximum manuscript upload size.", "metered": False, "reset_period": None},
    "manuscript.ingestion": {"value_type": "integer", "unit": "bytes", "description": "Manuscript ingestion volume.", "metered": True, "reset_period": "month", "customer_visible": False},
    "ai.chat": {"value_type": "boolean", "unit": None, "description": "Use grounded AI assistance.", "metered": False, "reset_period": None},
    "ai.chapter_review.monthly": {"value_type": "integer", "unit": "chapter_reviews", "description": "Deep chapter reviews per calendar month.", "metered": True, "reset_period": "month"},
    "ai.whole_thesis_review.monthly": {"value_type": "integer", "unit": "whole_thesis_reviews", "description": "Whole-thesis reviews per calendar month.", "metered": True, "reset_period": "month"},
    "export.docx": {"value_type": "boolean", "unit": None, "description": "Generate verified DOCX exports.", "metered": False, "reset_period": None},
    "export.pdf": {"value_type": "boolean", "unit": None, "description": "Generate verified PDF exports.", "metered": False, "reset_period": None},
    "export.pdf.monthly": {"value_type": "integer", "unit": "pdf_exports", "description": "Verified PDF exports per calendar month.", "metered": True, "reset_period": "month"},
    "review.supervisor": {"value_type": "boolean", "unit": None, "description": "Supervisor collaboration workflow.", "metered": False, "reset_period": None},
    "profile.custom": {"value_type": "boolean", "unit": None, "description": "Create custom formatting profiles.", "metered": False, "reset_period": None},
    "seat.student_limit": {"value_type": "integer", "unit": "student_seats", "description": "Maximum active student seats.", "metered": True, "reset_period": None},
    "seat.staff_limit": {"value_type": "integer", "unit": "staff_seats", "description": "Maximum active staff seats.", "metered": True, "reset_period": None},
    "retention.days": {"value_type": "integer", "unit": "days", "description": "Default draft retention period.", "metered": False, "reset_period": None},
    "support.priority": {"value_type": "string", "unit": None, "description": "Support service tier.", "metered": False, "reset_period": None},
}


def catalog_row(key: str) -> dict[str, Any] | None:
    value = ENTITLEMENT_CATALOG.get(key)
    if value is None:
        return None
    return {"key": key, "customer_visible": value.get("customer_visible", True), **value}
