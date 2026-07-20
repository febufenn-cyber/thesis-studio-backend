"""Tamil (and Indic) text must survive the full DOCX→PDF pipeline.

A Tamil Nadu college hits this the first week: theses quote Tamil primary
texts even when written in English. These tests lock the guarantee and the
deployment probe that makes missing fonts loud before a student finds them.
"""

from __future__ import annotations

import subprocess

import pytest

from app.renderers.fonts import script_coverage, soffice_path

TAMIL = "தமிழ் இலக்கியத்தில் நினைவும் வரலாறும்"


def test_script_coverage_probe_shape() -> None:
    coverage = script_coverage()
    assert set(coverage) >= {"tamil", "devanagari", "telugu", "kannada", "malayalam"}
    # Values are either a family name or None — never an exception.
    for family in coverage.values():
        assert family is None or isinstance(family, str)


def test_ci_environment_covers_tamil() -> None:
    """The reference environment must cover Tamil; if this fails, the deploy
    image regressed and real exports would show tofu."""
    coverage = script_coverage()
    assert coverage["tamil"], (
        "No Tamil-capable font installed — install fonts-noto-core/fonts-indic"
    )


@pytest.mark.asyncio
async def test_tamil_survives_docx_to_pdf(tmp_path) -> None:
    soffice = soffice_path()
    if not soffice:
        pytest.skip("LibreOffice not available")
    from docx import Document

    src = tmp_path / "tamil.docx"
    d = Document()
    d.add_paragraph(f"Control line. {TAMIL}.")
    d.save(str(src))
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(src)],
        capture_output=True, timeout=180,
    )
    pdf = tmp_path / "tamil.pdf"
    assert pdf.exists(), "PDF conversion failed"
    text = subprocess.run(
        ["pdftotext", str(pdf), "-"], capture_output=True, text=True, timeout=60
    ).stdout
    assert TAMIL.split()[0] in text, "Tamil text lost in DOCX→PDF conversion"
