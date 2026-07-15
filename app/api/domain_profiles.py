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
from app.domains.validators import ComplianceContext, PageInfo, run_profile
from app.models.project import Project
from app.services.export_service import build_thesis_document


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
    "reproducibility_checklist",
    "broader_impacts",
    "limitations",
    "ethics_statement",
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
        "validators": list(profile.validators),
        "page_limit": profile.page_limit,
        "enforced": profile.enforces(),
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


@router.get("/projects/{project_id}/domain-readiness")
async def project_domain_readiness(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Advisory submission-readiness for a project against its domain profile.

    Distinct from the Phase 2 review readiness at
    ``GET /projects/{id}/readiness`` (``review_workspace``): this endpoint
    reports section coverage against the project's chosen ``DomainProfile``,
    not review-item completeness. Kept on its own path so neither shadows the
    other in the router table.
    """
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


@router.get("/projects/{project_id}/compliance")
async def project_compliance(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Enforce the project's venue profile: page budget, anonymization, repro.

    Advisory by default (no profile / non-enforcing profile → soft ``ready``);
    a ``block`` finding means not submission-ready. Page count is estimated here
    (no PDF stack in this path); a real measurement can be supplied by the
    compile/seal path later.
    """
    project = await fetch_owned_project(db, project_id, current_user.id)

    key = (project.meta or {}).get("domain_profile")
    soft = {"profile": key or None, "enforced": False, "ready": True, "findings": [], "checklist": []}
    if not key:
        return soft
    try:
        profile = get_domain_profile(key)
    except UnknownDomainProfile:
        return {**soft, "profile": None}
    if not profile.enforces():
        return {**soft, "profile": profile.key, "checklist": list(profile.submission_checklist)}

    document = build_thesis_document(project)
    context = ComplianceContext(
        document=document,
        profile=profile,
        page_info=PageInfo(page_count=None, measured_by="estimate"),
        reproducibility_answers=(project.meta or {}).get("reproducibility", {}),
        present_sections=frozenset(_present_section_identifiers(project)),
    )
    findings = run_profile(context)
    return {
        "profile": profile.key,
        "enforced": True,
        "ready": not any(f.severity == "block" for f in findings),
        "page_limit": profile.page_limit,
        "findings": [f.to_dict() for f in findings],
        "checklist": list(profile.submission_checklist),
    }
