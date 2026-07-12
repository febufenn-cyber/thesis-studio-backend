#!/usr/bin/env python3
"""Fail CI when tracked text files contain credential-shaped values.

The signatures are assembled from fragments so this scanner does not match its
own source. Findings report only the path, line number and category; suspected
secret material is never echoed into CI logs.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Signature:
    label: str
    pattern: re.Pattern[str]


SIGNATURES = (
    Signature("api_token", re.compile(r"sk" + r"-[A-Za-z0-9_-]{20,}")),
    Signature("aws_access_key", re.compile(r"AK" + r"IA[0-9A-Z]{16}")),
    Signature(
        "private_key_header",
        re.compile(r"BEGIN " + r"(?:RSA|OPENSSH|EC) PRIVATE KEY"),
    ),
    Signature(
        "r2_secret_assignment",
        re.compile(r"R2_SECRET_ACCESS_" + r"KEY=[^$<{\s]"),
    ),
)


def _tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [root / value.decode("utf-8") for value in result.stdout.split(b"\0") if value]


def _is_excluded(path: Path) -> bool:
    return path.suffix.lower() == ".md" or path.name == ".env.example"


def scan_text(text: str) -> list[tuple[int, str]]:
    findings: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for signature in SIGNATURES:
            if signature.pattern.search(line):
                findings.append((line_number, signature.label))
    return findings


def scan_repository(root: Path) -> list[tuple[Path, int, str]]:
    findings: list[tuple[Path, int, str]] = []
    for path in _tracked_files(root):
        if _is_excluded(path) or not path.is_file():
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, label in scan_text(text):
            findings.append((path.relative_to(root), line_number, label))
    return findings


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    findings = scan_repository(root)
    if findings:
        for path, line_number, label in findings:
            print(f"secret-pattern: {path}:{line_number}: {label}")
        print(f"Secret-pattern check failed with {len(findings)} finding(s).")
        return 1
    print("Secret-pattern check passed: no credential-shaped values in tracked text files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
