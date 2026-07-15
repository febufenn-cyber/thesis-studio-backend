"""Pandoc universal document conversion (enterprise E6).

Wraps the pandoc binary to convert between document formats. Two integrity-safe
uses: exporting the *already-rendered* canonical manuscript to more formats
(odt, rst, epub, ...), and a non-mutating *preview* conversion of an uploaded
document (it never touches the citation registry or canonical model).

Safety posture:
- pandoc runs with ``--sandbox`` for text outputs so a malicious input cannot
  read arbitrary files (binary writers need pandoc's own data files, which
  ``--sandbox`` forbids), always under a wall-clock timeout and output-size cap.
- Formats are allow-listed; an unknown format is refused, not passed through.
- Fail-closed: if pandoc is absent or errors, callers raise/return an explicit
  error — never a fabricated or partial document presented as complete.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from app.core.config import get_settings

__all__ = [
    "PandocError",
    "PandocUnavailableError",
    "pandoc_available",
    "convert",
    "INPUT_FORMATS",
    "OUTPUT_FORMATS",
    "BINARY_OUTPUTS",
]


class PandocError(RuntimeError):
    """A pandoc conversion failed."""


class PandocUnavailableError(PandocError):
    """The pandoc binary is not installed or the feature is disabled."""


# Allow-listed formats. Kept deliberately conservative and text-forward.
INPUT_FORMATS = frozenset(
    {
        "markdown", "gfm", "commonmark", "latex", "html", "rst", "org",
        "mediawiki", "textile", "jats", "docbook", "docx", "odt", "epub",
        "bibtex", "ris", "csljson",
    }
)
OUTPUT_FORMATS = frozenset(
    {
        "markdown", "gfm", "commonmark", "latex", "html", "rst", "org",
        "mediawiki", "textile", "jats", "docbook", "plain", "docx", "odt",
        "epub", "rtf", "asciidoc",
    }
)
# Outputs that are binary and must be read as bytes from a file.
BINARY_OUTPUTS = frozenset({"docx", "odt", "epub", "rtf"})
# Inputs that are binary and must be written to a file for pandoc to read.
_BINARY_INPUTS = frozenset({"docx", "odt", "epub"})
# Readers that can pull external files/entities (\\input, \\include, XML external
# entities). Binary outputs run without --sandbox (pandoc needs its own data
# files), so pairing an include-capable reader with a binary writer is refused —
# it would let untrusted input read arbitrary host files into the output.
_INCLUDE_CAPABLE_INPUTS = frozenset({"latex", "html", "jats", "docbook"})

_MAX_OUTPUT_BYTES = 25 * 1024 * 1024


def _pandoc_bin() -> str | None:
    configured = getattr(get_settings(), "PANDOC_BIN", "pandoc") or "pandoc"
    return shutil.which(configured)


def pandoc_available() -> bool:
    """True when the feature is enabled and the pandoc binary is present."""
    if not getattr(get_settings(), "PANDOC_ENABLED", True):
        return False
    return _pandoc_bin() is not None


async def convert(content: str | bytes, *, from_fmt: str, to_fmt: str) -> bytes:
    """Convert ``content`` from ``from_fmt`` to ``to_fmt``; return raw bytes.

    Raises :class:`PandocUnavailableError` if pandoc is unavailable/disabled and
    :class:`PandocError` on an unsupported format, timeout, or conversion error.
    """
    if from_fmt not in INPUT_FORMATS:
        raise PandocError(f"Unsupported input format: {from_fmt}")
    if to_fmt not in OUTPUT_FORMATS:
        raise PandocError(f"Unsupported output format: {to_fmt}")
    if to_fmt in BINARY_OUTPUTS and from_fmt in _INCLUDE_CAPABLE_INPUTS:
        # Binary writers disable --sandbox; an include-capable reader could then
        # read host files. Refuse rather than widen the attack surface.
        raise PandocError(
            f"Converting {from_fmt} to a binary format ({to_fmt}) is not permitted; "
            "use a text output format instead."
        )
    binary = _pandoc_bin()
    if binary is None or not getattr(get_settings(), "PANDOC_ENABLED", True):
        raise PandocUnavailableError("pandoc is not available")

    timeout = float(getattr(get_settings(), "PANDOC_TIMEOUT_SECONDS", 20.0))
    data = content.encode("utf-8") if isinstance(content, str) else content

    with tempfile.TemporaryDirectory(prefix="pandoc-") as tmp:
        tmp_path = Path(tmp)
        args = [binary, "-f", from_fmt, "-t", to_fmt]
        # --sandbox blocks pandoc from reading any file except explicit inputs
        # (defends against malicious include directives). Binary writers
        # (docx/odt/epub/rtf) must read pandoc's bundled data files, which
        # --sandbox forbids, so it is applied only for text outputs.
        if to_fmt not in BINARY_OUTPUTS:
            args.insert(1, "--sandbox")

        # Binary inputs/outputs go through files; text streams via stdin/stdout.
        stdin_data: bytes | None = data
        if from_fmt in _BINARY_INPUTS:
            in_path = tmp_path / "input"
            in_path.write_bytes(data)
            args += [str(in_path)]
            stdin_data = None

        out_path: Path | None = None
        if to_fmt in BINARY_OUTPUTS:
            out_path = tmp_path / "output"
            args += ["-o", str(out_path)]
        else:
            args += ["-o", "-"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:  # binary vanished between check and exec
            raise PandocUnavailableError(f"pandoc could not be started: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data), timeout=timeout
            )
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise PandocError(f"pandoc timed out after {timeout:.0f}s") from exc

        if proc.returncode != 0:
            msg = (stderr or b"").decode("utf-8", "replace").strip() or "unknown error"
            raise PandocError(f"pandoc failed: {msg}")

        result = out_path.read_bytes() if out_path is not None else (stdout or b"")

    if len(result) > _MAX_OUTPUT_BYTES:
        raise PandocError("pandoc output exceeds the 25 MB limit")
    return result
