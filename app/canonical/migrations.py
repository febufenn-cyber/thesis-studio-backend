"""In-application migrations for canonical JSONB documents.

Alembic migrates relational tables. This module migrates the independently
versioned canonical JSON stored across Project columns and immutable snapshots.
"""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from app.canonical.model import CANONICAL_SCHEMA_VERSION, ThesisDocument


_STATUS_MAP = {
    "draft": "in_progress",
    "review": "needs_review",
}


def _identity(item: dict) -> None:
    item.setdefault("id", str(uuid4()))


def upgrade_canonical_payload(payload: dict, from_version: int | None = None) -> dict:
    """Return schema-v3 canonical JSON without mutating the caller's object."""

    data = deepcopy(payload or {})
    version = int(from_version or data.get("schema_version") or 2)

    if version <= 2:
        for entry in data.setdefault("front_matter", []):
            _identity(entry)
            entry["status"] = _STATUS_MAP.get(entry.get("status"), entry.get("status", "imported"))
            for block in entry.setdefault("body_blocks", []):
                _identity(block)
        for chapter in data.setdefault("chapters", []):
            _identity(chapter)
            chapter["status"] = _STATUS_MAP.get(
                chapter.get("status"), chapter.get("status", "imported")
            )
            for block in chapter.setdefault("blocks", []):
                _identity(block)
        disclosure = data.setdefault("meta", {}).setdefault("ai_disclosure", {})
        disclosure.setdefault("tools", [])
        disclosure.setdefault("assistance_types", [])
        version = 3

    data["schema_version"] = CANONICAL_SCHEMA_VERSION
    # Validation is part of migration: an invalid legacy payload is never saved.
    return ThesisDocument.model_validate(data).model_dump(mode="json")


def project_payload(project) -> dict:
    return upgrade_canonical_payload(
        {
            "schema_version": getattr(project, "canonical_schema_version", 2),
            "meta": project.meta or {},
            "front_matter": project.front_matter or [],
            "chapters": project.chapters or [],
            "works_cited": project.works_cited or [],
            "style_profile_id": str(project.style_profile_id) if project.style_profile_id else None,
        },
        getattr(project, "canonical_schema_version", 2),
    )


def apply_payload(project, payload: dict) -> ThesisDocument:
    upgraded = upgrade_canonical_payload(payload, payload.get("schema_version"))
    document = ThesisDocument.model_validate(upgraded)
    dumped = document.model_dump(mode="json")
    project.meta = dumped["meta"]
    project.front_matter = dumped["front_matter"]
    project.chapters = dumped["chapters"]
    project.works_cited = dumped["works_cited"]
    project.canonical_schema_version = CANONICAL_SCHEMA_VERSION
    return document
