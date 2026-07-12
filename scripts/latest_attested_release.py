"""Print the newest eligible attested APPLICATION release on main.

Eligible means: the commit is on origin/main, has a durable attestation at
release-candidates/<sha>.json with failures==0/errors==0/image_build passed,
and is NOT an attestation-only commit (one whose first-parent diff touches
nothing outside release-candidates/). Use this instead of copying SHAs by
hand into the release dispatch — stale hard-coded SHAs deploy old code, and
attestation SHAs deploy no code at all.

Usage:
    python scripts/latest_attested_release.py            # newest eligible SHA
    python scripts/latest_attested_release.py --verbose  # + attestation summary
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _is_attestation_only(sha: str) -> bool:
    """True when the commit's first-parent diff is confined to release-candidates/."""
    paths = _git("diff", "--name-only", f"{sha}^", sha).splitlines()
    return bool(paths) and all(p.startswith("release-candidates/") for p in paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--limit", type=int, default=50,
                        help="how many main commits to walk (newest first)")
    args = parser.parse_args()

    _git("fetch", "--quiet", "origin", "main")
    for sha in _git("log", "--format=%H", f"-{args.limit}", "origin/main").splitlines():
        try:
            raw = _git("show", f"origin/main:release-candidates/{sha}.json")
        except subprocess.CalledProcessError:
            continue
        report = json.loads(raw)
        if report.get("failures") != 0 or report.get("errors") != 0:
            continue
        if report.get("image_build") != "passed":
            continue
        if _is_attestation_only(sha):
            continue
        print(sha)
        if args.verbose:
            keys = ("tests", "failures", "errors", "skipped", "migration",
                    "image_build", "attested_at")
            print(json.dumps({k: report.get(k) for k in keys}, indent=2, sort_keys=True),
                  file=sys.stderr)
        return 0
    print("no eligible attested release found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
