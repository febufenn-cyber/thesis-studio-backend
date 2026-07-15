"""Corpus assembly with k-anonymity suppression (docs/LLD.md 3.8)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.project import Project
from app.research.anonymize import (
    anonymize_project,
    research_pseudonym,
    revision_fingerprint,
)
from app.research.consent import current_terms_version, has_research_consent


class ResearchGovernanceError(RuntimeError):
    """Corpus export is not permitted under the current governance gates."""


def _k() -> int:
    return int(getattr(get_settings(), "RESEARCH_K_ANONYMITY", 20))


def _bucket(record: dict) -> str:
    return f"{record.get('domain_profile','')}|{record.get('citation_style','')}|{record.get('locale','')}"


def k_anonymize(records: list[dict], *, k: int) -> tuple[list[dict], int]:
    """Suppress records whose quasi-identifier bucket has fewer than k members."""
    counts: dict[str, int] = {}
    for r in records:
        b = _bucket(r)
        counts[b] = counts.get(b, 0) + 1
    kept = [r for r in records if counts[_bucket(r)] >= k]
    return kept, len(records) - len(kept)


def _governance_ready() -> bool:
    settings = get_settings()
    return bool(
        getattr(settings, "RESEARCH_CORPUS_ENABLED", False)
        and getattr(settings, "RESEARCH_TERMS_VERSION", "")
        and getattr(settings, "RESEARCH_ETHICS_APPROVAL_REF", "")
    )


async def build_corpus(db: AsyncSession, *, scope: str = "revision_history", apply_k: bool = True) -> dict:
    """Assemble the de-identified corpus for consented projects.

    Fail-closed: raises unless all governance gates are set. Only projects whose
    owner has an active, current-terms consent for the scope are included.
    """
    if not _governance_ready():
        raise ResearchGovernanceError(
            "Corpus export requires RESEARCH_CORPUS_ENABLED, RESEARCH_TERMS_VERSION "
            "and RESEARCH_ETHICS_APPROVAL_REF to be set."
        )

    projects = list((await db.execute(select(Project))).scalars())
    records: list[dict] = []
    for project in projects:
        if not await has_research_consent(db, project.user_id, scope):
            continue
        payload = anonymize_project(project)
        payload["subject_ref"] = research_pseudonym(project.user_id)
        payload["revision_ref"] = revision_fingerprint(project.id, project.document_version or 1)
        records.append(payload)

    suppressed = 0
    if apply_k:
        records, suppressed = k_anonymize(records, k=_k())
    return {
        "terms_version": current_terms_version(),
        "record_count": len(records),
        "suppressed_count": suppressed,
        "records": records,
    }


async def shared_preview(db: AsyncSession, project: Project) -> dict:
    """What would be shared about one project (live anonymization; read-only)."""
    payload = anonymize_project(project)
    payload["subject_ref"] = research_pseudonym(project.user_id)
    return payload
