"""DOCX package safety and preservation preflight.

The scanner runs before python-docx parsing. It validates the ZIP package,
rejects decompression bombs, and enumerates document objects that the current
canonical model cannot reconstruct. Unsupported content is never silently
ignored: it is returned as explicit blocking/review issues in the import report.
"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal
from xml.etree import ElementTree as ET


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 120 * 1024 * 1024
MAX_ZIP_ENTRIES = 5000
MAX_COMPRESSION_RATIO = 200

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = {"w": W, "m": M}


class ManuscriptValidationError(ValueError):
    """The upload is unsafe, malformed, or not a DOCX document."""


@dataclass
class PreflightIssue:
    code: str
    severity: Literal["block", "review", "info"]
    count: int
    message: str
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "count": self.count,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass
class PreflightReport:
    counts: dict[str, int]
    issues: list[PreflightIssue]
    package: dict

    @property
    def blocking_count(self) -> int:
        return sum(i.count for i in self.issues if i.severity == "block")

    def as_dict(self) -> dict:
        return {
            "counts": self.counts,
            "issues": [i.as_dict() for i in self.issues],
            "package": self.package,
            "blocking_count": self.blocking_count,
        }


def _safe_member_name(name: str) -> bool:
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts


def _read_xml(zf: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        raw = zf.read(name)
    except KeyError:
        return None
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ManuscriptValidationError(f"Malformed DOCX XML: {name}") from exc


def _count(root: ET.Element | None, expression: str) -> int:
    return len(root.findall(expression, NS)) if root is not None else 0


def inspect_docx(path: str) -> PreflightReport:
    """Validate and inspect a DOCX package without extracting it to disk."""

    size = os.path.getsize(path)
    if size <= 0:
        raise ManuscriptValidationError("The uploaded manuscript is empty.")
    if size > MAX_UPLOAD_BYTES:
        raise ManuscriptValidationError(
            f"The manuscript exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit."
        )
    if not zipfile.is_zipfile(path):
        raise ManuscriptValidationError("The uploaded file is not a valid DOCX package.")

    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ManuscriptValidationError("The DOCX package contains too many files.")

        total_uncompressed = 0
        max_ratio = 0.0
        for info in infos:
            if not _safe_member_name(info.filename):
                raise ManuscriptValidationError("The DOCX package contains an unsafe path.")
            total_uncompressed += info.file_size
            ratio = info.file_size / max(info.compress_size, 1)
            max_ratio = max(max_ratio, ratio)
            if info.file_size > 1024 * 1024 and ratio > MAX_COMPRESSION_RATIO:
                raise ManuscriptValidationError("The DOCX package has a suspicious compression ratio.")
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise ManuscriptValidationError("The expanded DOCX package is too large to process safely.")

        names = set(zf.namelist())
        if "word/document.xml" not in names or "[Content_Types].xml" not in names:
            raise ManuscriptValidationError("The package is missing required DOCX components.")

        document = _read_xml(zf, "word/document.xml")
        footnotes = _read_xml(zf, "word/footnotes.xml")
        endnotes = _read_xml(zf, "word/endnotes.xml")
        comments = _read_xml(zf, "word/comments.xml")

        header_names = sorted(n for n in names if n.startswith("word/header") and n.endswith(".xml"))
        footer_names = sorted(n for n in names if n.startswith("word/footer") and n.endswith(".xml"))
        media_names = sorted(n for n in names if n.startswith("word/media/") and not n.endswith("/"))
        embedded_names = sorted(n for n in names if n.startswith("word/embeddings/") and not n.endswith("/"))

        counts = {
            "paragraphs": _count(document, ".//w:p"),
            "tables": _count(document, ".//w:tbl"),
            "drawings": _count(document, ".//w:drawing") + _count(document, ".//w:pict"),
            "images": len(media_names),
            "hyperlinks": _count(document, ".//w:hyperlink"),
            "page_breaks": len(
                [
                    e
                    for e in (document.findall(".//w:br", NS) if document is not None else [])
                    if e.attrib.get(f"{{{W}}}type") == "page"
                ]
            ),
            "section_breaks": _count(document, ".//w:sectPr"),
            "fields": _count(document, ".//w:fldSimple") + _count(document, ".//w:instrText"),
            "tracked_insertions": _count(document, ".//w:ins"),
            "tracked_deletions": _count(document, ".//w:del"),
            "lists": _count(document, ".//w:numPr"),
            "text_boxes": _count(document, ".//w:txbxContent"),
            "equations": _count(document, ".//m:oMath") + _count(document, ".//m:oMathPara"),
            "headers": len(header_names),
            "footers": len(footer_names),
            "footnotes": max(_count(footnotes, ".//w:footnote") - 2, 0),
            "endnotes": max(_count(endnotes, ".//w:endnote") - 2, 0),
            "comments": _count(comments, ".//w:comment"),
            "embedded_objects": len(embedded_names),
        }

        issues: list[PreflightIssue] = []

        def add(code: str, key: str, severity: Literal["block", "review", "info"], message: str, evidence: dict | None = None) -> None:
            if counts[key]:
                issues.append(
                    PreflightIssue(code, severity, counts[key], message, evidence or {})
                )

        add("unsupported_tables", "tables", "block", "Tables require explicit operator reconstruction before final export.")
        add("unsupported_images", "images", "block", "Images/figures and their placement are preserved only in the original manuscript.", {"members": media_names[:50]})
        add("unsupported_footnotes", "footnotes", "block", "Footnotes are not yet represented by the canonical model.")
        add("unsupported_endnotes", "endnotes", "block", "Endnotes are not yet represented by the canonical model.")
        add("unsupported_text_boxes", "text_boxes", "block", "Text-box content requires manual review and reconstruction.")
        add("unsupported_equations", "equations", "block", "Equations are not yet represented by the canonical model.")
        add("unsupported_embedded_objects", "embedded_objects", "block", "Embedded objects cannot be safely reconstructed.", {"members": embedded_names[:50]})
        add("tracked_changes_present", "tracked_insertions", "review", "Tracked insertions are present; accept/reject them in Word before relying on the import.")
        add("tracked_deletions_present", "tracked_deletions", "review", "Tracked deletions are present; deleted text may affect preservation accounting.")
        add("comments_present", "comments", "review", "Comments are preserved in the original manuscript but are not imported into the canonical document.")
        add("headers_present", "headers", "review", "Existing headers will be replaced by the selected format profile.", {"members": header_names})
        add("footers_present", "footers", "review", "Existing footers/page numbers will be replaced by the selected format profile.", {"members": footer_names})
        add("lists_present", "lists", "review", "Numbered or bulleted lists are flattened to paragraph text and require review.")
        add("hyperlinks_present", "hyperlinks", "info", "Hyperlink display text is imported; link targets remain in the original manuscript.")
        add("fields_present", "fields", "info", "Word fields such as an existing TOC/page numbers will be regenerated by Robofox.")

        return PreflightReport(
            counts=counts,
            issues=issues,
            package={
                "compressed_bytes": size,
                "uncompressed_bytes": total_uncompressed,
                "entry_count": len(infos),
                "max_compression_ratio": round(max_ratio, 2),
            },
        )
