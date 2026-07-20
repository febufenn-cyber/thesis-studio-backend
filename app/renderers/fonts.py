"""Font availability checks for the Thesis Studio export engine.

All filesystem/subprocess probing is done lazily inside the functions — import
never touches the filesystem so the module is safe to import on any machine.

Public API
----------
soffice_path() -> str | None
    Locate the LibreOffice ``soffice`` (or ``soffice.bin``) binary.

times_new_roman_available() -> bool
    Best-effort check that Times New Roman exists on the host.
    Returns ``True`` with a log warning when the check can't be performed
    conclusively (never hard-fails import or render startup).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known install locations for LibreOffice, searched in order.
# ---------------------------------------------------------------------------
_SOFFICE_CANDIDATES: list[str] = [
    # macOS drag-and-drop install
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    # macOS Homebrew cask
    "/opt/homebrew/opt/libreoffice/lib/libreoffice/program/soffice",
    # Linux — Debian/Ubuntu packages
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    # Linux — snap
    "/snap/bin/libreoffice",
    # Linux — flatpak wrapper script
    "/var/lib/flatpak/exports/bin/org.libreoffice.LibreOffice",
]

# Common macOS font directories (user and system).
_MACOS_FONT_DIRS: list[Path] = [
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
    Path.home() / "Library" / "Fonts",
]

# Fragment of the Times New Roman font filename we look for.
_TNR_NAME_FRAGMENT = "times new roman"


def soffice_path() -> str | None:
    """Return the absolute path to the LibreOffice ``soffice`` binary, or ``None``.

    Resolution order:
    1. ``SOFFICE_PATH`` environment variable (explicit override).
    2. ``shutil.which("soffice")`` — finds it if the directory is on ``PATH``.
    3. ``shutil.which("soffice.bin")`` — used on some Linux distributions.
    4. The hard-coded candidate list ``_SOFFICE_CANDIDATES``.

    Returns ``None`` if soffice cannot be located; callers should surface an
    actionable error (e.g. "install ``ttf-mscorefonts-installer`` and
    LibreOffice") rather than silently degrading.
    """
    # 1. Explicit env override.
    env_path = os.environ.get("SOFFICE_PATH")
    if env_path and Path(env_path).is_file():
        return env_path

    # 2 & 3. PATH lookup.
    for cmd in ("soffice", "soffice.bin"):
        found = shutil.which(cmd)
        if found:
            return found

    # 4. Hard-coded candidates.
    for candidate in _SOFFICE_CANDIDATES:
        if Path(candidate).is_file():
            return candidate

    logger.warning(
        "LibreOffice soffice binary not found. "
        "Install LibreOffice and ensure it is on PATH, or set SOFFICE_PATH."
    )
    return None


def times_new_roman_available() -> bool:
    """Return ``True`` if Times New Roman appears to be installed on this host.

    Strategy (tried in order, stops at first conclusive result):

    1. ``fc-list`` (fontconfig, present on Linux and macOS with XQuartz/Homebrew):
       ``fc-list | grep -i "times new roman"`` — conclusive either way.
    2. Scan macOS system font directories for a filename containing
       ``"times new roman"`` (case-insensitive).
    3. Fall back to ``True`` with a logged warning (never hard-fail) — the
       caller will discover the absence at render time via LibreOffice output.

    Notes
    -----
    On a vanilla Ubuntu server install, Times New Roman is absent unless
    ``ttf-mscorefonts-installer`` is installed.  The boot-time font check
    (DESIGN.md §9) should call this and emit install instructions when it
    returns ``False``.
    """
    # 1. fontconfig fc-list (Linux / macOS with fontconfig).
    fc_list = shutil.which("fc-list")
    if fc_list:
        try:
            result = subprocess.run(
                [fc_list],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return _TNR_NAME_FRAGMENT in result.stdout.lower()
            # fc-list failed — fall through to next strategy.
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("fc-list probe failed: %s", exc)

    # 2. Scan macOS font directories.
    for font_dir in _MACOS_FONT_DIRS:
        if not font_dir.is_dir():
            continue
        try:
            for entry in font_dir.iterdir():
                if _TNR_NAME_FRAGMENT in entry.name.lower():
                    return True
        except OSError as exc:
            logger.debug("Font directory scan failed for %s: %s", font_dir, exc)

    # 3. Inconclusive — assume present but warn.
    logger.warning(
        "Could not conclusively determine whether Times New Roman is installed. "
        "If PDF export produces font substitution, install ttf-mscorefonts-installer "
        "(Debian/Ubuntu: sudo apt-get install ttf-mscorefonts-installer) "
        "or the Microsoft core fonts package for your platform."
    )
    return True


# ---------------------------------------------------------------------------
# Complex-script coverage (DESIGN §9 / Tamil-first market requirement).
# ---------------------------------------------------------------------------

# One representative letter per script we promise to render. A thesis for a
# Tamil Nadu college will contain Tamil the day it is adopted; the other Indic
# scripts follow the same probe so the deployment checklist covers them too.
_SCRIPT_PROBES: dict[str, str] = {
    "tamil": "0B95",       # க
    "devanagari": "0915",  # क
    "telugu": "0C15",      # క
    "kannada": "0C95",     # ಕ
    "malayalam": "0D15",   # ക
}


def script_coverage() -> dict[str, str | None]:
    """Which installed font family would render each supported script.

    Uses ``fc-match :charset=XXXX`` per script. ``None`` means NO installed
    font covers the script — exports containing it will show tofu boxes.
    Never raises; on hosts without fontconfig every value is ``None`` and the
    caller should treat coverage as unknown-but-suspect.
    """
    fc_match = shutil.which("fc-match")
    coverage: dict[str, str | None] = {}
    for script, codepoint in _SCRIPT_PROBES.items():
        family: str | None = None
        if fc_match:
            try:
                result = subprocess.run(
                    [fc_match, "-f", "%{family}", f":charset={codepoint}"],
                    capture_output=True, text=True, timeout=10,
                )
                candidate = (result.stdout or "").strip()
                # fontconfig returns a last-resort face when nothing matches;
                # treat empty and LastResort as no coverage.
                if result.returncode == 0 and candidate and "lastresort" not in candidate.lower():
                    family = candidate
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.debug("fc-match probe failed for %s: %s", script, exc)
        coverage[script] = family
        if family is None:
            logger.warning(
                "No installed font covers %s (U+%s). Exports containing this "
                "script will render tofu. Install fonts-noto-core / fonts-indic "
                "(Debian/Ubuntu: sudo apt-get install fonts-noto-core fonts-indic).",
                script, codepoint,
            )
    return coverage
