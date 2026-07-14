"""Domain-profile catalog and per-project submission-readiness API.

Exposes the document-structure profiles defined in ``app.domains.profiles``
(section templates + submission checklists) and a best-effort readiness aid
that checks a project's canonical sections against its declared profile's
required sections. Readiness here is an advisory checklist, never a hard gate.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.domains.profiles import (
    UnknownDomainProfile,
    available_domain_profiles,
    get_domain_profile,
)
from app.models.project import Project


router = APIRouter(tags=["domain-profiles"])


_GENERIC_SECTIONS: tuple[str, ...] = (
    "title",
    "abstract",
    "references",
    "works_cited",
    "introduction",
    "methods",
    "results",
    "discussion",
    "conclusion",
)


@router.get("/domain-profiles")
async def list_domain_profiles(current_user: CurrentUser) -> dict:
    """Metadata for every registered domain profile (for profile pickers)."""
    return {"profiles": available_domain_profiles()}


@router.get("/domain-profiles/{key}")
async def get_domain_profile_detail(key: str, current_user: CurrentUser) -> dict:
    """Full detail for one profile; 404 if the key is not registered."""
    try:
        profile = get_domain_profile(key)
    except UnknownDomainProfile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown domain profile {key!r}",
        ) from None
    return {
        "key": profile.key,
        "label": profile.label,
        "credential": profile.credential,
        "default_citation_style": profile.default_citation_style,
        "sections": [
            {"name": s.name, "required": s.required, "repeatable": s.repeatable}
            for s in profile.sections
        ],
        "submission_checklist": list(profile.submission_checklist),
    }


def _present_section_identifiers(project: Project) -> set[str]:
    """Best-effort set of section identifiers considered present in a project."""
    front_matter = project.front_matter or []
    front_kinds = {
        str(entry["kind"])
        for entry in front_matter
        if isinstance(entry, dict) and entry.get("kind")
    }

    present: set[str] = set(front_kinds)

    chapters = project.chapters or []
    if chapters:
        present.add("chapters")

    chapter_titles = [
        str(ch.get("title", "")).lower() for ch in chapters if isinstance(ch, dict)
    ]

    for name in _GENERIC_SECTIONS:
        if name in front_kinds:
            present.add(name)
            continue
        needle = name.replace("_", " ")
        if any(needle in title or name in title for title in chapter_titles):
            present.add(name)

    return present


@router.get("/projects/{project_id}/readiness")
async def project_readiness(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Advisory submission-readiness for a project against its domain profile."""
    project = await fetch_owned_project(db, project_id, current_user.id)

    key = (project.meta or {}).get("domain_profile")
    if not key:
        return {"profile": None, "ready": True, "missing_sections": [], "checklist": []}

    try:
        profile = get_domain_profile(key)
    except UnknownDomainProfile:
        return {"profile": None, "ready": True, "missing_sections": [], "checklist": []}

    present = _present_section_identifiers(project)
    missing_sections = [name for name in profile.required_sections() if name not in present]
    return {
        "profile": profile.key,
        "ready": not missing_sections,
        "missing_sections": missing_sections,
        "checklist": list(profile.submission_checklist),
    }
