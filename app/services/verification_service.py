"""Combined academic, preservation and format verification.

This service is the single export gate. It combines the citation verifier,
open import issues, metadata/profile requirements and post-render output QA.
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
from app.models.manuscript_revision import ManuscriptRevision
from app.models.project import Project
from app.models.quote import Quote
from app.models.source import Source
from app.models.style_profile import StyleProfile
from app.renderers.phase1_profiles import resolve_phase1_profile
from app.renderers.profiles import ResolvedProfile


class ExportBlockedError(RuntimeError):
    def __init__(self, report: dict):
        self.report = report
        count = report.get("counts", {}).get("block", 0)
        super().__init__(f"Export blocked by {count} unresolved issue(s).")


def _value(meta: Any, path: str) -> Any:
    current = meta
    for part in path.split("."):
        current = getattr(current, part)
    return current


def _format_violations(
    document: ThesisDocument,
    project: Project,
    profile: ResolvedProfile,
    revision: ManuscriptRevision | None,
) -> list[dict]:
    violations: list[dict] = []

    def add(
        rule: str,
        found: str,
        expected: str,
        severity: str = "block",
        location: dict | None = None,
    ) -> None:
        violations.append(
            {
                "rule": rule,
                "location": location or {"section": "document"},
                "found": found,
                "expected": expected,
                "severity": severity,
            }
        )

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
            add(
                "required_metadata_missing",
                path,
                f"a non-empty value for {path}",
                location={"section": "metadata", "field": path},
            )

    if not document.chapters:
        add("chapters_missing", "0 chapters", "at least one chapter")
    chapter_numbers: set[int] = set()
    for chapter in document.chapters:
        location = {"chapter": chapter.number, "chapter_id": str(chapter.id)}
        if not chapter.title.strip():
            add("chapter_title_missing", "blank title", "a chapter title", location=location)
        if chapter.number in chapter_numbers:
            add(
                "duplicate_chapter_number",
                str(chapter.number),
                "unique chapter numbers",
                location=location,
            )
        chapter_numbers.add(chapter.number)

    actual_kinds = [entry.kind for entry in document.front_matter]
    expected_order = list(profile.front_matter_order)
    for required_kind in expected_order:
        if required_kind not in actual_kinds:
            add(
                "front_matter_missing",
                required_kind,
                "required front-matter section present",
                location={"section": "front_matter", "kind": required_kind},
            )
    ordered_subset = [kind for kind in actual_kinds if kind in expected_order]
    if ordered_subset != sorted(ordered_subset, key=expected_order.index):
        add(
            "front_matter_order",
            " → ".join(ordered_subset),
            " → ".join(expected_order),
            location={"section": "front_matter"},
        )

    if "contents" in expected_order and not profile.toc.native_word_field:
        add(
            "toc_not_authoritative",
            "static contents list without computed page numbers",
            "a native Word TOC field updated during final rendering",
        )

    if document.schema_version != CANONICAL_SCHEMA_VERSION:
        add(
            "canonical_schema_outdated",
            str(document.schema_version),
            str(CANONICAL_SCHEMA_VERSION),
        )

    if revision is None:
        add(
            "manuscript_revision_missing",
            "no active immutable revision",
            "an uploaded manuscript revision applied to the project",
        )
    else:
        report = revision.import_report or {}
        for issue in report.get("issues", []):
            if issue.get("status", "open") == "resolved":
                continue
            mapped = "info" if issue.get("severity") == "info" else "block"
            add(
                f"import_{issue.get('code', 'issue')}",
                issue.get("message", "Open import issue"),
                "operator resolves or acknowledges the import issue",
                mapped,
                {"section": "import_report", "issue_id": issue.get("id")},
            )
        preservation = report.get("preservation", {})
        if preservation.get("paragraph_coverage", 0) < 1:
            add(
                "preservation_coverage_incomplete",
                str(preservation.get("paragraph_coverage")),
                "1.0 paragraph preservation coverage",
            )

    return violations


async def verify_project(db: AsyncSession, project: Project) -> dict:
    document = ThesisDocument.model_validate(
        {
            "meta": project.meta or {},
            "front_matter": project.front_matter or [],
            "chapters": project.chapters or [],
            "works_cited": project.works_cited or [],
        }
    )
    source_rows = list(
        (
            await db.execute(
                select(Source).where(
                    Source.project_id == project.id,
                    Source.user_id == project.user_id,
                )
            )
        ).scalars()
    )
    quote_rows = list(
        (
            await db.execute(
                select(Quote).where(
                    Quote.project_id == project.id,
                    Quote.user_id == project.user_id,
                )
            )
        ).scalars()
    )
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
    profile_version = style_version or governed_version

    academic = verify_academic(
        document,
        {source.id: source for source in source_rows},
        {quote.id: quote for quote in quote_rows},
    ).as_dict()
    format_violations = _format_violations(document, project, profile, revision)
    combined = list(academic["violations"]) + format_violations
    counts = {
        "block": sum(1 for violation in combined if violation["severity"] == "block"),
        "warn": sum(1 for violation in combined if violation["severity"] == "warn"),
        "info": sum(1 for violation in combined if violation["severity"] == "info"),
    }
    return {
        "pass": counts["block"] == 0,
        "document_version": project.document_version,
        "manuscript_revision_id": str(project.active_revision_id) if project.active_revision_id else None,
        "profile": project.format_profile,
        "profile_version": profile_version,
        "profile_notes": profile.notes,
        "counts": counts,
        "violations": combined,
        "academic": academic,
        "import_report": revision.import_report if revision else None,
    }


def post_render_qa(
    output_path: str,
    fmt: str,
    document: ThesisDocument,
    profile: ResolvedProfile,
) -> dict:
    violations: list[dict] = []

    def add(rule: str, found: str, expected: str) -> None:
        violations.append(
            {
                "rule": rule,
                "location": {"section": "rendered_output"},
                "found": found,
                "expected": expected,
                "severity": "block",
            }
        )

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        add("output_missing", output_path, "a non-empty rendered artifact")
        return {"pass": False, "violations": violations}

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
            rendered_text = "\n".join(paragraph.text for paragraph in rendered.paragraphs)
            for marker in (
                "[VERIFY:",
                "[QUOTE_NEEDED:",
                "[UNSUPPORTED:",
                "[REVIEW_REQUIRED:",
            ):
                if marker in rendered_text:
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
        "pass": not violations,
        "violations": violations,
        "size_bytes": os.path.getsize(output_path),
    }
