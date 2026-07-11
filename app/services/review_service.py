"""Persistent review inbox and transparent readiness calculations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.manuscript_revision import ManuscriptRevision
from app.models.project import Project
from app.models.review_item import ReviewItem
from app.services.verification_service import verify_project


class ReviewResolutionError(RuntimeError):
    pass


_CATEGORY_BY_PREFIX = (
    ("required_metadata", "metadata"),
    ("front_matter", "front_matter"),
    ("toc_", "formatting"),
    ("chapter", "structure"),
    ("duplicate_chapter", "structure"),
    ("citation_", "citation"),
    ("cited_source", "citation"),
    ("quote_", "quotation"),
    ("wc_", "works_cited"),
    ("unresolved_marker", "structure"),
    ("import_unsupported", "unsupported"),
    ("import_", "import"),
    ("preservation_", "preservation"),
    ("manuscript_revision", "import"),
    ("canonical_schema", "structure"),
)


_WHY = {
    "metadata": "Required submission details feed institution-controlled title, certificate and declaration pages.",
    "front_matter": "Institutional front matter must be complete and ordered before final pagination is trustworthy.",
    "structure": "A structural mistake can move meaning, comments and later AI proposals to the wrong location.",
    "citation": "An ambiguous or missing citation breaks the evidence chain between prose and bibliography.",
    "quotation": "Direct quotations must remain exact and traceable to a human-verified registry record.",
    "works_cited": "Bibliographic fields must be confirmed; the system must never invent missing publication data.",
    "formatting": "The final output must be rendered by the governed profile rather than a browser approximation.",
    "unsupported": "Unsupported Word objects cannot be silently dropped from a polished final document.",
    "preservation": "Every non-empty source paragraph must be accounted for or explicitly handled.",
    "import": "The parser surfaced a decision that requires human judgment.",
}


def _category(rule: str) -> str:
    for prefix, category in _CATEGORY_BY_PREFIX:
        if rule.startswith(prefix):
            return category
    return "export_readiness"


def _human_title(rule: str) -> str:
    special = {
        "required_metadata_missing": "Required metadata is missing",
        "chapters_missing": "No chapters are available",
        "chapter_title_missing": "Chapter title is missing",
        "duplicate_chapter_number": "Chapter number is duplicated",
        "citation_ambiguous_source": "Citation matches multiple sources",
        "citation_without_source": "Citation has no matching source",
        "cited_source_missing_from_wc": "Cited source is absent from Works Cited",
        "quote_missing_id": "Quotation is not linked to the registry",
        "quote_unverified": "Quotation has not been human-verified",
        "quote_text_divergence": "Document quotation differs from registry copy",
        "wc_entry_verify_fields": "Bibliography fields require confirmation",
        "wc_source_unverified": "Source has not been verified",
        "wc_raw_entry_requires_confirmation": "Preserved raw bibliography entry needs confirmation",
        "wc_entry_uncited": "Works Cited entry is not cited",
        "unresolved_marker": "Editorial marker remains unresolved",
        "manuscript_revision_missing": "No immutable manuscript revision is active",
        "preservation_coverage_incomplete": "Source preservation coverage is incomplete",
    }
    return special.get(rule, rule.replace("_", " ").strip().capitalize())


def _actions(category: str, rule: str, location: dict) -> list[dict]:
    if category == "metadata":
        return [{"action": "open_metadata", "label": "Complete metadata"}]
    if category == "citation":
        return [
            {"action": "open_block", "label": "Open citation in context"},
            {"action": "resolve_citation", "label": "Choose source"},
        ]
    if category == "quotation":
        return [
            {"action": "open_block", "label": "Compare quotation"},
            {"action": "open_registry", "label": "Open quotation registry"},
        ]
    if category == "works_cited":
        return [{"action": "edit_source", "label": "Review source fields"}]
    if category in {"unsupported", "preservation", "import"}:
        return [{"action": "review_import", "label": "Review original import evidence"}]
    if location.get("block_id"):
        return [{"action": "open_block", "label": "Open block"}]
    if location.get("chapter_id"):
        return [{"action": "open_chapter", "label": "Open chapter"}]
    return [{"action": "open_review", "label": "Review details"}]


def _stable_location(location: dict) -> dict:
    # Array indexes are intentionally excluded: stable UUIDs are the anchor.
    return {
        key: value
        for key, value in (location or {}).items()
        if key not in {"block_index"} and value is not None
    }


def _fingerprint(rule: str, location: dict, revision_id: UUID | None) -> str:
    payload = {
        "rule": rule,
        "location": _stable_location(location),
        "revision_id": str(revision_id) if revision_id and rule.startswith("import_") else None,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _uuid(value) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def _component_scores(project: Project, report: dict) -> dict:
    violations = report.get("violations", [])
    by_category: dict[str, list[dict]] = {}
    for finding in violations:
        by_category.setdefault(_category(finding["rule"]), []).append(finding)

    required_metadata = 10 if project.doc_type in {
        "ma_dissertation", "mphil_dissertation", "phd_thesis"
    } else 2
    missing_meta = len(by_category.get("metadata", []))
    metadata = max(0, round(100 * (required_metadata - min(required_metadata, missing_meta)) / required_metadata))

    chapters = max(1, len(project.chapters or []))
    structure_defects = len(by_category.get("structure", [])) + len(by_category.get("front_matter", []))
    structure = max(0, round(100 * (chapters - min(chapters, structure_defects)) / chapters))

    import_report = report.get("import_report") or {}
    citation_total = int((import_report.get("summary") or {}).get("in_text_citations", 0))
    citation_open = len(by_category.get("citation", []))
    citations = 100 if citation_total == 0 else max(
        0, round(100 * (citation_total - min(citation_total, citation_open)) / citation_total)
    )

    quote_total = int(report.get("active_quotes", 0))
    quote_open = len(by_category.get("quotation", []))
    quotations = 100 if quote_total == 0 else max(
        0, round(100 * (quote_total - min(quote_total, quote_open)) / quote_total)
    )

    format_open = len(by_category.get("formatting", []))
    formatting = max(0, 100 - min(100, format_open * 20))

    unsupported_open = len(by_category.get("unsupported", [])) + len(by_category.get("preservation", []))
    unsupported = 100 if unsupported_open == 0 else max(0, 100 - unsupported_open * 25)

    components = {
        "structure": structure,
        "metadata": metadata,
        "citations": citations,
        "quotations": quotations,
        "formatting": formatting,
        "unsupported": unsupported,
    }
    components["overall"] = round(sum(components.values()) / len(components))
    components["formula"] = (
        "Transparent completion average across structure, metadata, citations, "
        "quotations, formatting and unsupported-content handling. A single block "
        "still makes the project not ready regardless of percentage."
    )
    components["ready"] = report.get("counts", {}).get("block", 0) == 0
    return components


async def sync_review_items(db: AsyncSession, project: Project) -> tuple[list[ReviewItem], dict, dict]:
    report = await verify_project(db, project)
    revision_id = project.active_revision_id
    existing = list(
        (
            await db.execute(
                select(ReviewItem).where(
                    ReviewItem.project_id == project.id,
                    ReviewItem.user_id == project.user_id,
                )
            )
        ).scalars()
    )
    by_fingerprint = {item.fingerprint: item for item in existing}
    seen: set[str] = set()
    now = datetime.now(timezone.utc)

    for finding in report.get("violations", []):
        rule = finding["rule"]
        location = _stable_location(finding.get("location") or {})
        fingerprint = _fingerprint(rule, location, revision_id)
        seen.add(fingerprint)
        category = _category(rule)
        block_id = _uuid(location.get("block_id"))
        source_id = _uuid(location.get("source_id"))
        quote_id = _uuid(finding.get("found")) if rule.startswith("quote_") else None
        item = by_fingerprint.get(fingerprint)
        if item is None:
            item = ReviewItem(
                project_id=project.id,
                user_id=project.user_id,
                revision_id=revision_id if rule.startswith("import_") else None,
                block_id=block_id,
                source_id=source_id,
                quote_id=quote_id,
                fingerprint=fingerprint,
                category=category,
                rule=rule,
                severity=finding.get("severity", "block"),
                title=_human_title(rule),
                explanation=f"Found: {finding.get('found', '')}. Expected: {finding.get('expected', '')}.",
                why_it_matters=_WHY.get(category, "This finding affects submission readiness."),
                location=location,
                recommended_actions=_actions(category, rule, location),
                evidence={"found": finding.get("found"), "expected": finding.get("expected")},
                status="open",
                first_seen_version=project.document_version,
                last_seen_version=project.document_version,
            )
            db.add(item)
            by_fingerprint[fingerprint] = item
        else:
            item.category = category
            item.severity = finding.get("severity", "block")
            item.title = _human_title(rule)
            item.explanation = f"Found: {finding.get('found', '')}. Expected: {finding.get('expected', '')}."
            item.why_it_matters = _WHY.get(category, item.why_it_matters)
            item.location = location
            item.recommended_actions = _actions(category, rule, location)
            item.evidence = {"found": finding.get("found"), "expected": finding.get("expected")}
            item.last_seen_version = project.document_version
            item.block_id = block_id
            item.source_id = source_id
            item.quote_id = quote_id
            item.updated_at = now
            if item.status in {"resolved", "acknowledged", "superseded"}:
                history = list(item.resolution_history or [])
                history.append(
                    {
                        "event": "reopened_by_verifier",
                        "at": now.isoformat(),
                        "document_version": project.document_version,
                    }
                )
                item.resolution_history = history
                item.status = "open"
                item.resolution_note = None
                item.resolved_at = None
                item.resolved_by = None

    for item in existing:
        if item.fingerprint not in seen and item.status in {"open", "acknowledged"}:
            item.status = "superseded"
            item.updated_at = now

    await db.flush()
    rows = list(
        (
            await db.execute(
                select(ReviewItem)
                .where(
                    ReviewItem.project_id == project.id,
                    ReviewItem.user_id == project.user_id,
                )
                .order_by(
                    ReviewItem.status.asc(),
                    ReviewItem.severity.asc(),
                    ReviewItem.created_at.asc(),
                )
            )
        ).scalars()
    )
    return rows, report, _component_scores(project, report)


async def resolve_review_item(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    item: ReviewItem,
    *,
    action: str,
    note: str,
    expected_version: int,
) -> ReviewItem:
    if project.document_version != expected_version:
        raise ReviewResolutionError("Project changed in another session. Reload before resolving.")
    now = datetime.now(timezone.utc)

    if action == "reopen":
        item.status = "open"
        item.resolution_note = note
        item.resolved_at = None
        item.resolved_by = None
    elif item.rule.startswith("import_"):
        if item.category == "preservation" or "unaccounted" in item.rule:
            raise ReviewResolutionError(
                "Preservation failures cannot be acknowledged away. Restore or account for the missing content."
            )
        if action not in {"resolve", "acknowledge"}:
            raise ReviewResolutionError("Unsupported review action.")
        revision = (
            await db.execute(
                select(ManuscriptRevision).where(
                    ManuscriptRevision.id == project.active_revision_id,
                    ManuscriptRevision.project_id == project.id,
                    ManuscriptRevision.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        issue_id = (item.location or {}).get("issue_id")
        if revision is None or not issue_id:
            raise ReviewResolutionError("The underlying import issue is no longer available.")
        report = dict(revision.import_report or {})
        issues = [dict(issue) for issue in report.get("issues", [])]
        target = next((issue for issue in issues if issue.get("id") == issue_id), None)
        if target is None:
            raise ReviewResolutionError("The underlying import issue no longer exists.")
        target["status"] = "resolved"
        target["resolution"] = {
            "note": note,
            "action": action,
            "resolved_by": str(user_id),
            "resolved_at": now.isoformat(),
        }
        report["issues"] = issues
        report.setdefault("summary", {})["issues_open"] = sum(
            1 for issue in issues if issue.get("status") != "resolved"
        )
        report["summary"]["issues_blocking"] = sum(
            1
            for issue in issues
            if issue.get("status") != "resolved" and issue.get("severity") == "block"
        )
        revision.import_report = report
        item.status = "acknowledged" if action == "acknowledge" else "resolved"
        item.resolution_note = note
        item.resolved_at = now
        item.resolved_by = user_id
    elif item.severity in {"warn", "info"} and action == "acknowledge":
        item.status = "acknowledged"
        item.resolution_note = note
        item.resolved_at = now
        item.resolved_by = user_id
    else:
        raise ReviewResolutionError(
            "This finding is generated from the current document. Fix the underlying content, source, quotation or metadata; it cannot be dismissed manually."
        )

    history = list(item.resolution_history or [])
    history.append(
        {
            "event": action,
            "note": note,
            "at": now.isoformat(),
            "user_id": str(user_id),
            "document_version_before": project.document_version,
        }
    )
    item.resolution_history = history
    project.document_version += 1
    item.last_seen_version = project.document_version
    db.add(
        Event(
            project_id=project.id,
            user_id=user_id,
            kind="review_item_updated",
            data={
                "review_item_id": str(item.id),
                "rule": item.rule,
                "action": action,
                "document_version": project.document_version,
            },
        )
    )
    await db.commit()
    await db.refresh(item)
    return item
