"""Stable commercial catalog shared by migrations, APIs, restores and tests."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commercial import EntitlementDefinition, ProductEdition, ServiceComponent


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


PRODUCT_EDITIONS = {
    "student": ("student", "Robofox Student", "One governed thesis workspace for an individual student."),
    "operator": ("operator", "Robofox Operator", "Multi-project professional formatting and client delivery."),
    "institution": ("institution", "Robofox Institution", "Department and institution collaboration, governance and procurement."),
}


SERVICE_COMPONENTS = {
    "web": ("Web application", "Application shell and project navigation."),
    "auth": ("Authentication", "OTP, identity and revocable sessions."),
    "editing": ("Document editing", "Canonical document reads and saves."),
    "ai": ("AI assistance", "Grounded AI queue and provider capacity."),
    "ingestion": ("Manuscript ingestion", "Upload preflight and deterministic parsing."),
    "pdf": ("Preview and PDF generation", "Dedicated rendering and conversion workers."),
    "downloads": ("File downloads", "Verified export and sealed-package downloads."),
    "email": ("Email notifications", "OTP and workflow notifications."),
}


def catalog_row(key: str) -> dict[str, Any] | None:
    value = ENTITLEMENT_CATALOG.get(key)
    if value is None:
        return None
    return {"key": key, "customer_visible": value.get("customer_visible", True), **value}


async def ensure_commercial_catalog(db: AsyncSession) -> dict[str, int]:
    """Idempotently restore seed metadata after fresh ORM creation or recovery."""
    existing_entitlements = set((await db.execute(select(EntitlementDefinition.key))).scalars())
    existing_editions = set((await db.execute(select(ProductEdition.slug))).scalars())
    existing_components = set((await db.execute(select(ServiceComponent.key))).scalars())
    created = {"entitlements": 0, "editions": 0, "components": 0}
    for key, data in ENTITLEMENT_CATALOG.items():
        if key in existing_entitlements:
            continue
        db.add(
            EntitlementDefinition(
                key=key,
                value_type=data["value_type"],
                unit=data.get("unit"),
                description=data["description"],
                customer_visible=data.get("customer_visible", True),
                metered=data.get("metered", False),
                reset_period=data.get("reset_period"),
            )
        )
        created["entitlements"] += 1
    for slug, (audience, name, description) in PRODUCT_EDITIONS.items():
        if slug in existing_editions:
            continue
        db.add(ProductEdition(slug=slug, audience=audience, name=name, description=description, state="published"))
        created["editions"] += 1
    for key, (name, description) in SERVICE_COMPONENTS.items():
        if key in existing_components:
            continue
        db.add(ServiceComponent(key=key, name=name, description=description, public_status=True, state="operational", metadata_json={}))
        created["components"] += 1
    if any(created.values()):
        await db.commit()
    return created
