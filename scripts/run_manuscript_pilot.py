"""Run the real-manuscript pilot harness over DOCX fixtures.

For each .docx the harness runs the repo's own ingestion pipeline —
``app.ingest.preflight.inspect_docx`` → ``app.ingest.docx_extract.extract_paragraphs``
→ ``app.ingest.structure.parse_manuscript`` → ``app.ingest.citations``
(``parse_wc_entries`` + ``scan_document``) — then attempts a canonical→DOCX render
via ``app.renderers.docx_renderer.render_docx`` with the default profile.

It records preservation accounting, unsupported-content reporting, citation
ambiguities/[VERIFY] fields and a fabrication check against the release thresholds
in docs/release/REAL_MANUSCRIPT_PILOT.md. Per-file JSON results are written under
``--out`` plus one aggregate ``pilot_report.json``.

Privacy rule: no manuscript text is ever written to stdout or the reports —
identifiers, counts, field names and checksums only. Malware scanning is forced
to ``disabled`` for local pilot runs and recorded as such in the report.

Usage:
    python scripts/run_manuscript_pilot.py --fixtures tests/fixtures/pilot --out <dir>
    python scripts/run_manuscript_pilot.py --file some.docx --out <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Local pilot policy: never attempt a network malware scan, never run as prod.
# Placeholders below only apply when the variables are absent from the process
# environment; they exist so the harness can run without real secrets.
os.environ["MALWARE_SCAN_MODE"] = "disabled"
os.environ["ENV"] = "development"
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://pilot:pilot@localhost:5453/pilot_unused"
)
os.environ.setdefault("JWT_SECRET", "pilot-harness-local-" + "0" * 40)
os.environ.setdefault("ANTHROPIC_API_KEY", "pilot-placeholder-key")

from docx import Document  # noqa: E402

from app.canonical.model import (  # noqa: E402
    CANONICAL_SCHEMA_VERSION as MODEL_SCHEMA_VERSION,
    BlockQuoteBlock,
    HeadingBlock,
    VerseQuoteBlock,
)
from app.core.config import get_settings  # noqa: E402
from app.ingest.citations import (  # noqa: E402
    VERIFY,
    parse_wc_entries,
    resolve_citation,
    scan_document,
)
from app.ingest.docx_extract import extract_paragraphs  # noqa: E402
from app.ingest.preflight import ManuscriptValidationError, inspect_docx  # noqa: E402
from app.ingest.structure import PARSER_VERSION, ParseResult, parse_manuscript  # noqa: E402
from app.renderers.docx_renderer import render_docx  # noqa: E402
from app.renderers.profiles import resolve_profile  # noqa: E402

PENDING = "pending-human-review"
MALWARE_NOTE = (
    "malware scanning disabled for this local pilot run (MALWARE_SCAN_MODE=disabled);"
    " production policy requires ClamAV"
)
# Preflight counts key → the issue code that must report it (block severity).
_UNSUPPORTED_CODES = {
    "tables": "unsupported_tables",
    "images": "unsupported_images",
    "footnotes": "unsupported_footnotes",
    "endnotes": "unsupported_endnotes",
    "text_boxes": "unsupported_text_boxes",
    "equations": "unsupported_equations",
    "embedded_objects": "unsupported_embedded_objects",
}


def _sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm(value: str) -> str:
    """Normalise text for read-vs-fabricated substring comparison."""
    value = (
        value.replace("–", "-").replace("—", "-").replace("’", "'")
        .replace("“", '"').replace("”", '"')
    )
    return re.sub(r"\s+", " ", value).strip().lower()


def _safe_error(exc: BaseException) -> str:
    """Return an error description safe for reports (type + truncated message)."""
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def _accounted_indexes(result: ParseResult) -> set[int]:
    """Every source paragraph index the parse classified or reported."""
    accounted: set[int] = set(result.structural_paragraph_indexes)
    for entry in result.document.front_matter:
        if entry.source_paragraph_index is not None:
            accounted.add(entry.source_paragraph_index)
        for block in entry.body_blocks:
            if block.source_paragraph_index is not None:
                accounted.add(block.source_paragraph_index)
    for chapter in result.document.chapters:
        if chapter.source_paragraph_index is not None:
            accounted.add(chapter.source_paragraph_index)
        if chapter.title_source_paragraph_index is not None:
            accounted.add(chapter.title_source_paragraph_index)
        for block in chapter.blocks:
            if block.source_paragraph_index is not None:
                accounted.add(block.source_paragraph_index)
    for paragraph_index, _runs in result.wc_raw_entries:
        accounted.add(paragraph_index)
    return accounted


def _fabricated_fields(candidates: list) -> list[dict]:
    """Fields that were neither read from the raw entry nor marked [VERIFY].

    Inherited authors from '---.' same-author repeats are accepted only when the
    candidate carries a verify note (flagged for human confirmation). Field
    values are never emitted — only kind and field name.
    """
    failures: list[dict] = []
    for candidate in candidates:
        raw_normalised = _norm(candidate.raw_entry)
        for field_name, value in candidate.fields.items():
            text = str(value)
            if not text.strip() or VERIFY in text:
                continue
            if _norm(text) in raw_normalised:
                continue
            if (
                field_name == "author"
                and candidate.raw_entry.startswith("---")
                and candidate.verify_note
            ):
                continue
            failures.append({"kind": candidate.kind, "field": field_name})
    return failures


def _load_manifest(fixtures_dir: Path | None) -> dict[str, dict]:
    """Return manifest records keyed by file name ({} when absent)."""
    if fixtures_dir is None:
        return {}
    manifest_path = fixtures_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {record["file"]: record for record in data.get("fixtures", [])}


def run_file(path: Path, expect_reject: bool, renders_dir: Path,
             profile_name: str) -> dict:
    """Run the full pipeline over one file and return its evidence record."""
    settings = get_settings()
    started = time.monotonic()
    result: dict = {
        "pilot_id": path.stem,
        "file": path.name,
        "consent_permission_record": (
            "synthetic fixture generated by scripts/generate_pilot_fixtures.py"
            " (no real manuscript; consent not applicable)"
        ),
        "original_sha256": _sha256(path),
        "file_size_bytes": path.stat().st_size,
        "page_count": "not-computed (harness does not paginate)",
        "institution_profile_and_version": (
            f"builtin:{profile_name} (renderer {settings.RENDERER_VERSION})"
        ),
        "expect_preflight_reject": expect_reject,
        "notes": [],
        "reviewer_identity": PENDING,
        "visual_comparison": PENDING,
        "human_corrections_required": PENDING,
        "final_verifier_result": (
            "not-run (harness scope: preflight/extract/structure/citations/render)"
        ),
        "pdf_checksum": "not-attempted (LibreOffice-gated; out of harness scope)",
        "pdf_pagination_manually_checked": PENDING,
        "original_vs_final_content_loss_review": PENDING,
        "operator_sign_off": PENDING,
        "student_academic_reviewer_sign_off": PENDING,
    }

    # --- Preflight -----------------------------------------------------------
    try:
        report = inspect_docx(str(path))
    except ManuscriptValidationError as exc:
        result.update({
            "preflight_rejected": True,
            "rejection_reason": _safe_error(exc),
            "upload_malware_result": f"n/a (preflight rejected); {MALWARE_NOTE}",
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        })
        return result
    result["preflight_rejected"] = False
    result["upload_malware_result"] = {
        "status": report.package["malware_scan"]["status"],
        "engine": report.package["malware_scan"]["engine"],
        "note": MALWARE_NOTE,
    }
    result["preflight_object_counts"] = report.counts
    result["preflight_package"] = report.package
    result["preflight_issues"] = [
        {"code": issue.code, "severity": issue.severity, "count": issue.count}
        for issue in report.issues
    ]
    result["preflight_blocking_count"] = report.blocking_count

    expected_unsupported = sorted(
        code for key, code in _UNSUPPORTED_CODES.items() if report.counts.get(key)
    )
    reported_codes = sorted({issue.code for issue in report.issues})
    result["unsupported_objects_reported"] = {
        "expected_from_counts": expected_unsupported,
        "reported_issue_codes": reported_codes,
        "all_reported": all(code in reported_codes for code in expected_unsupported),
    }
    if report.counts.get("tracked_insertions") or report.counts.get("tracked_deletions"):
        result["notes"].append(
            "tracked-change text is not imported by the extractor; preflight"
            " reports it as a review issue (not silent loss)"
        )
    if report.counts.get("tables"):
        result["notes"].append(
            "table cell text sits outside the body paragraph stream; tables are"
            " reported as unsupported (block) and excluded from the paragraph"
            " accounting below"
        )

    # --- Extraction + structure ---------------------------------------------
    try:
        paras = extract_paragraphs(str(path))
        parse_result = parse_manuscript(paras)
    except Exception as exc:  # pipeline failure is itself pilot evidence
        result["pipeline_error"] = {"stage": "extract/structure",
                                    "error": _safe_error(exc)}
        result["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
        return result

    source_indexes = {p.index for p in paras}
    accounted = _accounted_indexes(parse_result)
    unaccounted = sorted(source_indexes - accounted)
    result["parser_version"] = PARSER_VERSION
    result["canonical_schema_version_config"] = settings.CANONICAL_SCHEMA_VERSION
    result["canonical_model_schema_version"] = MODEL_SCHEMA_VERSION
    result["non_empty_source_text_accounted_for"] = {
        "source_nonempty_paragraphs": len(paras),
        "accounted_paragraphs": len(source_indexes & accounted),
        "unaccounted_paragraph_indexes": unaccounted,
        "fully_accounted": not unaccounted,
    }

    document = parse_result.document
    result["chapter_boundary_findings"] = {
        "chapters": len(document.chapters),
        "chapter_numbers": [c.number for c in document.chapters],
        "front_matter_kinds": [e.kind for e in document.front_matter],
        "parse_notes": list(parse_result.parse_notes),
    }
    headings = [b for c in document.chapters for b in c.blocks
                if isinstance(b, HeadingBlock)]
    result["heading_findings"] = {
        "level2": sum(1 for h in headings if h.level == 2),
        "level3": sum(1 for h in headings if h.level == 3),
    }
    block_quotes = [b for c in document.chapters for b in c.blocks
                    if isinstance(b, BlockQuoteBlock)]
    verse_quotes = [b for c in document.chapters for b in c.blocks
                    if isinstance(b, VerseQuoteBlock)]
    quotes = block_quotes + verse_quotes
    result["quotations_linked_unlinked"] = {
        "block_quotes": len(block_quotes),
        "verse_quotes": len(verse_quotes),
        "with_citation": sum(1 for q in quotes if q.citation),
        "without_citation": sum(1 for q in quotes if not q.citation),
    }

    # --- Citations ------------------------------------------------------------
    try:
        candidates = parse_wc_entries(parse_result.wc_raw_entries)
        in_text = scan_document(document)
    except Exception as exc:
        result["pipeline_error"] = {"stage": "citations", "error": _safe_error(exc)}
        result["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
        return result

    verify_fields = sum(
        1 for c in candidates for v in c.fields.values() if VERIFY in str(v)
    )
    fabricated = _fabricated_fields(candidates)
    result["works_cited"] = {
        "entries": len(candidates),
        "kinds": sorted({c.kind for c in candidates}),
        "verify_fields": verify_fields,
        "fully_structured": sum(1 for c in candidates
                                if c.parse_status == "fully_structured"),
        "structured_with_review": sum(1 for c in candidates
                                      if c.parse_status == "structured_with_review"),
        "fabricated_fields": fabricated,
    }

    sources = {uuid4(): c for c in candidates}
    resolution_reasons: dict[str, int] = {}
    auto_resolved_ambiguous = 0
    ambiguous_requiring_human = 0
    for citation in in_text:
        resolved_id, _cands, reason = resolve_citation(citation, sources)
        resolution_reasons[reason] = resolution_reasons.get(reason, 0) + 1
        if reason.startswith("ambiguous"):
            ambiguous_requiring_human += 1
            if resolved_id is not None:
                auto_resolved_ambiguous += 1
    result["citation_ambiguities"] = {
        "structural_ambiguities": len(parse_result.ambiguous),
        "structural_reasons": sorted({a.reason for a in parse_result.ambiguous}),
        "in_text_citations": len(in_text),
        "resolution_reasons": resolution_reasons,
        "ambiguous_requiring_human_decision": ambiguous_requiring_human,
        "auto_resolved_ambiguous": auto_resolved_ambiguous,
    }

    # --- Canonical → DOCX render ----------------------------------------------
    render_record: dict = {
        "attempted": True,
        "works_cited_included": False,
        "note": (
            "works cited omitted from the render: registry linking and [VERIFY]"
            " confirmation are human steps that precede a final export"
        ),
    }
    render_path = renders_dir / f"{path.stem}__render.docx"
    try:
        profile = resolve_profile(profile_name, None)
        render_docx(document, {}, profile, str(render_path))
        render_record["success"] = True
        render_record["output_sha256"] = _sha256(render_path)
        try:
            reopened = Document(str(render_path))
            render_record["reopened_successfully"] = True
            render_record["reopened_paragraphs"] = len(reopened.paragraphs)
        except Exception as exc:
            render_record["reopened_successfully"] = False
            render_record["reopen_error"] = _safe_error(exc)
    except Exception as exc:
        render_record["success"] = False
        render_record["error"] = _safe_error(exc)
    result["docx_render"] = render_record
    result["docx_checksum"] = render_record.get("output_sha256", "n/a (render failed)")
    result["docx_reopened_successfully"] = render_record.get(
        "reopened_successfully", False
    )

    result["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    return result


def _thresholds(results: list[dict]) -> dict:
    """Evaluate the REAL_MANUSCRIPT_PILOT.md release thresholds over *results*."""

    def failing(predicate) -> list[str]:
        return [r["file"] for r in results if predicate(r)]

    processed = [r for r in results if not r.get("preflight_rejected")]

    t_text = failing(
        lambda r: not r.get("preflight_rejected")
        and not r.get("non_empty_source_text_accounted_for", {}).get("fully_accounted")
    )
    t_unsupported = failing(
        lambda r: not r.get("preflight_rejected")
        and not r.get("unsupported_objects_reported", {}).get("all_reported")
    )
    t_fabricated = failing(
        lambda r: bool(r.get("works_cited", {}).get("fabricated_fields"))
    )
    t_ambiguous = failing(
        lambda r: r.get("citation_ambiguities", {}).get("auto_resolved_ambiguous", 0) > 0
    )
    t_render = failing(
        lambda r: not r.get("preflight_rejected")
        and not (
            r.get("docx_render", {}).get("success")
            and r.get("docx_render", {}).get("reopened_successfully")
        )
    )
    t_reject = failing(
        lambda r: r.get("expect_preflight_reject") != r.get("preflight_rejected", False)
    )
    t_errors = failing(lambda r: bool(r.get("pipeline_error")))

    return {
        "zero_silently_discarded_nonempty_text": {
            "pass": not t_text, "failing_files": t_text,
            "checked_files": len(processed),
        },
        "zero_unsupported_objects_omitted": {
            "pass": not t_unsupported, "failing_files": t_unsupported,
            "checked_files": len(processed),
        },
        "zero_fabricated_bibliographic_fields": {
            "pass": not t_fabricated, "failing_files": t_fabricated,
            "checked_files": len(processed),
        },
        "every_ambiguous_citation_requires_human_decision": {
            "pass": not t_ambiguous, "failing_files": t_ambiguous,
            "checked_files": len(processed),
        },
        "final_docx_renders_and_reopens": {
            "pass": not t_render, "failing_files": t_render,
            "checked_files": len(processed),
        },
        "malformed_and_bomb_rejected_by_preflight": {
            "pass": not t_reject, "failing_files": t_reject,
            "checked_files": len(results),
        },
        "no_pipeline_errors": {
            "pass": not t_errors, "failing_files": t_errors,
            "checked_files": len(results),
        },
        "final_pdf_checked": PENDING,
        "discrepancies_have_stable_issues": PENDING,
    }


def main() -> int:
    """Run the pilot over --fixtures (or --file), writing JSON evidence to --out."""
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fixtures", type=Path, help="Directory of .docx fixtures")
    group.add_argument("--file", type=Path, help="A single .docx file")
    parser.add_argument("--out", type=Path, required=True,
                        help="Directory for per-file JSON + pilot_report.json")
    parser.add_argument("--profile", default="tn_university",
                        help="Base render profile (default: tn_university)")
    args = parser.parse_args()

    fixtures_dir = args.fixtures.resolve() if args.fixtures else None
    single_file = args.file.resolve() if args.file else None
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    renders_dir = out_dir / "renders"
    renders_dir.mkdir(exist_ok=True)
    os.chdir(REPO_ROOT)  # Settings loads .env relative to the repo root.

    if fixtures_dir is not None:
        files = sorted(fixtures_dir.glob("*.docx"))
        manifest = _load_manifest(fixtures_dir)
    else:
        files = [single_file]
        manifest = _load_manifest(single_file.parent)
    if not files:
        print("no .docx files found", file=sys.stderr)
        return 2

    settings = get_settings()
    results: list[dict] = []
    for path in files:
        record = manifest.get(path.name, {})
        expect_reject = bool(record.get("expect_preflight_reject", False))
        result = run_file(path, expect_reject, renders_dir, args.profile)
        result["case"] = record.get("case", path.stem)
        results.append(result)
        (out_dir / f"{path.stem}.json").write_text(
            json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
        )
        status = "REJECTED" if result.get("preflight_rejected") else "processed"
        print(f"{path.name}: {status} ({result.get('duration_ms', '?')} ms)")

    thresholds = _thresholds(results)
    automated = [v for v in thresholds.values() if isinstance(v, dict)]
    overall_pass = all(v["pass"] for v in automated)
    aggregate = {
        "harness": "scripts/run_manuscript_pilot.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": (
            "synthetic fixtures only — real institutional manuscripts remain"
            " outstanding"
        ),
        "parser_version": PARSER_VERSION,
        "canonical_schema_version_config": settings.CANONICAL_SCHEMA_VERSION,
        "canonical_model_schema_version": MODEL_SCHEMA_VERSION,
        "renderer_version": settings.RENDERER_VERSION,
        "render_profile": args.profile,
        "malware_scan": {"mode": "disabled", "note": MALWARE_NOTE},
        "fixture_count": len(results),
        "rejected_files": [r["file"] for r in results
                           if r.get("preflight_rejected")],
        "thresholds": thresholds,
        "overall_pass": overall_pass,
        "reviewer_identity": PENDING,
        "visual_comparison": PENDING,
        "results": results,
    }
    report_path = out_dir / "pilot_report.json"
    report_path.write_text(
        json.dumps(aggregate, indent=2, default=str) + "\n", encoding="utf-8"
    )

    print(f"\naggregate: {report_path}")
    for name, verdict in thresholds.items():
        if isinstance(verdict, dict):
            mark = "PASS" if verdict["pass"] else "FAIL"
            extra = f" ({', '.join(verdict['failing_files'])})" \
                if verdict["failing_files"] else ""
            print(f"  {mark}  {name}{extra}")
        else:
            print(f"  {verdict}  {name}")
    print(f"overall (automated thresholds): {'PASS' if overall_pass else 'FAIL'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
