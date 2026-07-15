"""De-identification for the research corpus.

Pseudonyms are derived over the privacy pepper (unforgeable without the secret),
and project snapshots are reduced to structural features — block counts, origin
mix, marker kinds, citation-style/source-type histograms — with all authored
prose and identifying metadata stripped. No raw text or author identifier leaves.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from app.core.config import get_settings

_PII_META = ("candidate", "college", "guide", "hod", "title")
_PII_FRONT_MATTER = {"acknowledgement", "certificate", "declaration", "title_page"}


def research_pseudonym(user_id: UUID, *, salt: str = "subject") -> str:
    """Stable, non-reversible donor id over the privacy pepper."""
    pepper = get_settings().effective_privacy_hash_pepper
    return hashlib.sha256(f"{pepper}\x00{salt}\x00{user_id}".encode()).hexdigest()


def revision_fingerprint(project_id: UUID, document_version: int) -> str:
    return hashlib.sha256(f"{project_id}\x00{document_version}".encode()).hexdigest()


def _generalize_month(value) -> str:
    """Coarsen an exact year to its decade bucket."""
    text = str(value or "")
    digits = "".join(c for c in text if c.isdigit())[:4]
    if len(digits) == 4:
        return f"{digits[:3]}0s"
    return ""


def anonymize_project(project) -> dict:
    """Reduce a project to de-identified structural features only."""
    chapters = project.chapters or []
    origin_counts: dict[str, int] = {}
    marker_kinds: dict[str, int] = {}
    total_blocks = 0
    block_type_counts: dict[str, int] = {}

    for chapter in chapters:
        for block in chapter.get("blocks", []) if isinstance(chapter, dict) else []:
            total_blocks += 1
            origin = block.get("origin") or "unknown"
            origin_counts[origin] = origin_counts.get(origin, 0) + 1
            btype = block.get("type", "unknown")
            block_type_counts[btype] = block_type_counts.get(btype, 0) + 1
            if btype == "marker":
                kind = block.get("kind", "unknown")
                marker_kinds[kind] = marker_kinds.get(kind, 0) + 1

    meta = project.meta or {}
    submission = meta.get("submission") or {}
    return {
        "chapters": len(chapters),
        "total_blocks": total_blocks,
        "origin_counts": origin_counts,
        "block_type_counts": block_type_counts,
        "marker_kinds": marker_kinds,
        "citation_style": meta.get("citation_style", ""),
        "domain_profile": meta.get("domain_profile", ""),
        "locale": meta.get("locale", ""),
        "works_cited_count": len(project.works_cited or []),
        "submission_decade": _generalize_month(submission.get("year")),
    }


def assert_no_pii(payload: dict) -> None:
    """Defensive check used in tests: no known PII field name leaks into output."""
    for key in _PII_META:
        assert key not in payload, f"PII field {key} leaked into anonymized payload"
