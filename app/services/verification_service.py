"""Combined academic, preservation and format verification.

Only manual registry rows plus rows belonging to the active immutable
manuscript revision may influence verification. Old revisions remain stored
for restoration but cannot satisfy the current document's checks.
"""

from __future__ import annotations

import os
import zipfile
from typing import Any

from docx import Document
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.canonical.model import CANONICAL_SCHEMA_VERSION, ThesisDocument
from app.ingest.verifier import verify as verify_academic
from app.models.citation_resolution import CitationResolution
from app.models.manuscript_revision import ManuscriptRevision
from app.models.project import Project
from app.models.quote import Quote
from app.models.source import Source
from app.models.style_profile import StyleProfile
from app.renderers.phase1_profiles import resolve_phase1_profile
from app.renderers.profiles import ResolvedProfile
from app.services.registry_scope import active_resolution_rows, active_revision_rows


class ExportBlockedError(RuntimeError):
    def __init__(self, report: dict):
        self.report = report
        super().__init__(
            f"Export blocked by {report.get('counts', {}).get('block', 0)} unresolved issue(s)."
        )


def _value(meta: Any, path: str) -> Any:
    current = meta
    for part in path.split("."):
        current = getattr(current, part)
    return current


def _violation(
    rule: str,
    found: str,
    expected: str,
    severity: str = "block",
    location: dict | None = None,
) -> dict:
    return {
        "rule": rule,
        "location": location or {"section": "document"},
        "found": found,
        "expected": expected,
        "severity": severity,
    }


def _format_violations(
    document: ThesisDocument,
    project: Project,
    profile: ResolvedProfile,
    revision: ManuscriptRevision | None,
) -> list[dict]:
    findings: list[dict] = []
    required = ["title", "candidate.name"]
    if project.doc_type in {"ma_dissertation", "mphil_dissertation", "phd_thesis"}:
        required += [
            "candidate.reg_no",
            "degree",
            "department",
            "college.name",
            "college.affiliation",
            "college.city",
            "guide.name",
            "submission.month",
            "submission.year",
        ]
    for path in required:
        value = _value(document.meta, path)
        if value is None or not str(value).strip():
            findings.append(
                _violation(
                    "required_metadata_missing",
                    path,
                    f"a non-empty value for {path}",
                    location={"section": "metadata", "field": path},
                )
            )

    if not document.chapters:
        findings.append(_violation("chapters_missing", "0 chapters", "at least one chapter"))
    seen_numbers: set[int] = set()
    for chapter in document.chapters:
        location = {"chapter": chapter.number, "chapter_id": str(chapter.id)}
        if not chapter.title.strip():
            findings.append(
                _violation("chapter_title_missing", "blank title", "a chapter title", location=location)
            )
        if chapter.number in seen_numbers:
            findings.append(
                _violation(
                    "duplicate_chapter_number",
                    str(chapter.number),
                    "unique chapter numbers",
                    location=location,
                )
            )
        seen_numbers.add(chapter.number)

    actual = [entry.kind for entry in document.front_matter]
    expected = list(profile.front_matter_order)
    for kind in expected:
        if kind not in actual:
            findings.append(
                _violation(
                    "front_matter_missing",
                    kind,
                    "required front-matter section present",
                    location={"section": "front_matter", "kind": kind},
                )
            )
    ordered_subset = [kind for kind in actual if kind in expected]
    if ordered_subset != sorted(ordered_subset, key=expected.index):
        findings.append(
            _violation(
                "front_matter_order",
                " → ".join(ordered_subset),
                " → ".join(expected),
                location={"section": "front_matter"},
            )
        )
    if "contents" in expected and not profile.toc.native_word_field:
        findings.append(
            _violation(
                "toc_not_authoritative",
                "static contents list without computed page numbers",
                "a native Word TOC field updated during final rendering",
            )
        )
    if document.schema_version != CANONICAL_SCHEMA_VERSION:
        findings.append(
            _violation(
                "canonical_schema_outdated",
                str(document.schema_version),
                str(CANONICAL_SCHEMA_VERSION),
            )
        )

    if revision is None:
        findings.append(
            _violation(
                "manuscript_revision_missing",
                "no active immutable revision",
                "an uploaded manuscript revision applied to the project",
            )
        )
        return findings

    report = revision.import_report or {}
    for issue in report.get("issues", []):
        if issue.get("status", "open") == "resolved":
            continue
        severity = "info" if issue.get("severity") == "info" else "block"
        findings.append(
            _violation(
                f"import_{issue.get('code', 'issue')}",
                issue.get("message", "Open import issue"),
                "operator resolves or acknowledges the import issue",
                severity,
                {"section": "import_report", "issue_id": issue.get("id")},
            )
        )
    preservation = report.get("preservation", {})
    if preservation.get("paragraph_coverage", 0) < 1:
        findings.append(
            _violation(
                "preservation_coverage_incomplete",
                str(preservation.get("paragraph_coverage")),
                "1.0 paragraph preservation coverage",
            )
        )
    return findings


async def _resolve_profile(
    db: AsyncSession, project: Project
) -> tuple[ResolvedProfile, str]:
    override = None
    style_version = None
    if project.style_profile_id:
        style = (
            await db.execute(
                select(StyleProfile).where(StyleProfile.id == project.style_profile_id)
            )
        ).scalar_one_or_none()
        if style:
            override = style.data
            style_version = f"style:{style.id}:{style.created_at.isoformat()}"
    profile, governed_version = resolve_phase1_profile(project.format_profile, override)
    return profile, style_version or governed_version


async def verify_project(db: AsyncSession, project: Project) -> dict:
    document = ThesisDocument.model_validate(
        {
            "meta": project.meta or {},
            "front_matter": project.front_matter or [],
            "chapters": project.chapters or [],
            "works_cited": project.works_cited or [],
        }
    )
    all_sources = list(
        (
            await db.execute(
                select(Source).where(
                    Source.project_id == project.id,
                    Source.user_id == project.user_id,
                )
            )
        ).scalars()
    )
    all_quotes = list(
        (
            await db.execute(
                select(Quote).where(
                    Quote.project_id == project.id,
                    Quote.user_id == project.user_id,
                )
            )
        ).scalars()
    )
    all_resolutions = list(
        (
            await db.execute(
                select(CitationResolution).where(
                    CitationResolution.project_id == project.id,
                    CitationResolution.user_id == project.user_id,
                )
            )
        ).scalars()
    )
    sources = active_revision_rows(all_sources, project.active_revision_id)
    quotes = active_revision_rows(all_quotes, project.active_revision_id)
    resolutions = active_resolution_rows(all_resolutions, project.active_revision_id)
    resolution_map = {
        (str(row.block_id), row.raw_citation): row.source_id for row in resolutions
    }

    revision = None
    if project.active_revision_id:
        revision = (
            await db.execute(
                select(ManuscriptRevision).where(
                    ManuscriptRevision.id == project.active_revision_id,
                    ManuscriptRevision.project_id == project.id,
                    ManuscriptRevision.user_id == project.user_id,
                )
            )
        ).scalar_one_or_none()

    profile, profile_version = await _resolve_profile(db, project)
    academic = verify_academic(
        document,
        {source.id: source for source in sources},
        {quote.id: quote for quote in quotes},
        resolution_map,
    ).as_dict()
    combined = list(academic["violations"]) + _format_violations(
        document, project, profile, revision
    )
    counts = {
        "block": sum(1 for finding in combined if finding["severity"] == "block"),
        "warn": sum(1 for finding in combined if finding["severity"] == "warn"),
        "info": sum(1 for finding in combined if finding["severity"] == "info"),
    }
    return {
        "pass": counts["block"] == 0,
        "document_version": project.document_version,
        "manuscript_revision_id": (
            str(project.active_revision_id) if project.active_revision_id else None
        ),
        "profile": project.format_profile,
        "profile_version": profile_version,
        "profile_notes": profile.notes,
        "counts": counts,
        "violations": combined,
        "academic": academic,
        "active_sources": len(sources),
        "active_quotes": len(quotes),
        "citation_resolutions": len(resolutions),
        "import_report": revision.import_report if revision else None,
    }


def post_render_qa(
    output_path: str,
    fmt: str,
    document: ThesisDocument,
    profile: ResolvedProfile,
) -> dict:
    findings: list[dict] = []

    def add(rule: str, found: str, expected: str) -> None:
        findings.append(
            _violation(
                rule,
                found,
                expected,
                location={"section": "rendered_output"},
            )
        )

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        add("output_missing", output_path, "a non-empty rendered artifact")
        return {"pass": False, "violations": findings}

    if fmt == "docx":
        try:
            rendered = Document(output_path)
        except Exception as exc:
            add("docx_unreadable", type(exc).__name__, "DOCX reopens successfully")
        else:
            if not rendered.sections:
                add("docx_no_sections", "0", "at least one document section")
            else:
                section = rendered.sections[0]
                margins = profile.page.margins_in
                observed = {
                    "top": round(section.top_margin.inches, 2),
                    "bottom": round(section.bottom_margin.inches, 2),
                    "left": round(section.left_margin.inches, 2),
                    "right": round(section.right_margin.inches, 2),
                }
                expected = {
                    "top": margins.top,
                    "bottom": margins.bottom,
                    "left": margins.left,
                    "right": margins.right,
                }
                if any(abs(observed[key] - expected[key]) > 0.05 for key in expected):
                    add("margin_mismatch", str(observed), str(expected))
            text = "\n".join(paragraph.text for paragraph in rendered.paragraphs)
            for marker in (
                "[VERIFY:",
                "[QUOTE_NEEDED:",
                "[UNSUPPORTED:",
                "[REVIEW_REQUIRED:",
            ):
                if marker in text:
                    add(
                        "unresolved_marker_rendered",
                        marker,
                        "no unresolved marker in final output",
                    )
            if "contents" in profile.front_matter_order and profile.toc.native_word_field:
                with zipfile.ZipFile(output_path) as package:
                    xml = package.read("word/document.xml")
                if b" TOC " not in xml:
                    add("toc_field_missing", "no TOC field", "native Word TOC field")
    elif fmt == "pdf":
        with open(output_path, "rb") as handle:
            if handle.read(5) != b"%PDF-":
                add("pdf_header_invalid", "missing %PDF header", "a valid PDF artifact")

    return {
        "pass": not findings,
        "violations": findings,
        "size_bytes": os.path.getsize(output_path),
    }
