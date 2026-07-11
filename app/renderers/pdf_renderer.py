"""PDF renderer — LibreOffice headless conversion of the rendered DOCX.

Synchronous module: always call through asyncio.to_thread from async code.
Availability-gated: raises SofficeUnavailableError when LibreOffice is not
installed (DESIGN §9 requires deterministic conversion, no browser engines).
"""

from __future__ import annotations

import os
import subprocess

from app.renderers.fonts import soffice_path, times_new_roman_available


class SofficeUnavailableError(Exception):
    """LibreOffice (soffice) is not installed on this host."""


class PdfConversionError(Exception):
    """soffice ran but produced no usable PDF."""


def convert_to_pdf(docx_path: str, output_dir: str, timeout: int = 120) -> str:
    """Convert *docx_path* to PDF in *output_dir*; returns the PDF path."""
    soffice = soffice_path()
    if soffice is None:
        raise SofficeUnavailableError(
            "PDF rendering unavailable on this server (LibreOffice not installed)."
        )
    proc = subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", output_dir,
         docx_path],
        capture_output=True,
        timeout=timeout,
    )
    pdf_path = os.path.join(
        output_dir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
    )
    if proc.returncode != 0 or not os.path.exists(pdf_path) or not os.path.getsize(pdf_path):
        stderr_tail = (proc.stderr or b"").decode(errors="replace")[-200:]
        raise PdfConversionError(f"soffice conversion failed: {stderr_tail}")
    return pdf_path


def check_pdf_stack() -> dict:
    """Diagnostics: whether soffice and Times New Roman are available."""
    return {
        "soffice": soffice_path() is not None,
        "times_new_roman": times_new_roman_available(),
    }
