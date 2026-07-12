"""Verify profile version pinning across the registry, schema, and live rows.

Subphase E (institution profile sign-off tooling). Three layers of checks:

1. **Registry** — every profile registered in
   ``app.renderers.phase1_profiles.PROFILE_LABELS`` must resolve to a
   ``(profile, version_label)`` pair whose label carries an explicit version
   token (e.g. ``mcc_ma_english_2026:v1``).
2. **Source** — static confirmation (no imports of app.db, so no env needed)
   that the Export model defines ``profile_version`` and that the export
   pipeline records it plus a manifest ``format_profile_version``.
3. **Database (read-only)** — against ``--database-url`` (default: the local
   test DB): published/approved ``institutional_profile_versions`` rows carry
   a version and label; projects pinned to an institutional profile version
   also received a materialised ``style_profile_id`` (migration 0016 trigger);
   ready ``exports`` rows record a non-empty, non-default ``profile_version``
   and a manifest ``format_profile_version``.

Known structural gaps are reported honestly (not patched) — see the GAP
section in the output. Exit codes: 0 = no row-level violations, 1 = registry
or row violations found (or, with ``--strict``, structural gaps), 2 = usage
error. DB unreachable is reported and skipped unless ``--strict``.

Output policy: identifiers, counts and checksums only — never document prose.

Usage::

    .venv-validate/bin/python scripts/check_profile_pinning.py
    .venv-validate/bin/python scripts/check_profile_pinning.py \
        --database-url postgresql://thesis:thesis@localhost:5452/thesis_studio
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import asyncpg  # noqa: E402

from app.renderers.phase1_profiles import PROFILE_LABELS, resolve_phase1_profile  # noqa: E402

DEFAULT_DB_URL = "postgresql://thesis:thesis@localhost:5453/thesis_studio_test"

# Version labels must end in an explicit version token: v<digits> optionally
# prefixed (e.g. "v1", "compat-unverified-v1").
_VERSION_TOKEN = re.compile(r"v\d+$")


def normalise_db_url(url: str) -> str:
    """Strip the SQLAlchemy '+asyncpg' driver suffix for raw asyncpg use."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


# ---------------------------------------------------------------------------
# Layer 1 — registry
# ---------------------------------------------------------------------------


def check_registry() -> list[str]:
    """Verify every registered profile resolves with an explicit version label."""
    violations: list[str] = []
    print("== Registry (app/renderers/phase1_profiles.py) ==")
    for name in sorted(PROFILE_LABELS):
        try:
            _, version_label = resolve_phase1_profile(name)
        except Exception as exc:
            violations.append(f"registry: {name} failed to resolve ({type(exc).__name__})")
            print(f"  {name:<28} RESOLVE FAILED: {type(exc).__name__}")
            continue
        versioned = ":" in version_label and bool(
            _VERSION_TOKEN.search(version_label.rsplit(":", 1)[-1])
        )
        marker = "ok " if versioned else "VIOLATION"
        print(f"  {name:<28} version={version_label:<36} [{marker}]")
        if not versioned:
            violations.append(f"registry: {name} has no explicit version token ({version_label})")
    print()
    return violations


# ---------------------------------------------------------------------------
# Layer 2 — source-level pinning wiring
# ---------------------------------------------------------------------------


def check_source_wiring() -> list[str]:
    """Statically confirm the model column and service writes for pinning."""
    violations: list[str] = []
    print("== Source wiring (static) ==")
    checks = (
        ("app/models/export.py", "profile_version", "Export.profile_version column"),
        ("app/services/export_service.py", "export_row.profile_version =",
         "export pipeline records profile_version"),
        ("app/services/export_service.py", '"format_profile_version"',
         "export manifest records format_profile_version"),
        ("app/models/institutional_governance.py", "profile_version_id",
         "submission packages pin institutional profile version id"),
    )
    for rel_path, needle, label in checks:
        path = REPO_ROOT / rel_path
        present = path.exists() and needle in path.read_text(encoding="utf-8")
        print(f"  {label:<52} [{'ok' if present else 'VIOLATION'}]")
        if not present:
            violations.append(f"source: {label} not found in {rel_path}")
    print()
    return violations


# ---------------------------------------------------------------------------
# Layer 3 — database rows (read-only)
# ---------------------------------------------------------------------------


async def check_database(db_url: str) -> tuple[list[str], bool]:
    """Run read-only row checks; return (violations, db_reachable)."""
    violations: list[str] = []
    print(f"== Database rows ({db_url.rsplit('@', 1)[-1]}) ==")
    try:
        conn = await asyncpg.connect(db_url, timeout=10)
    except (OSError, asyncpg.PostgresError, asyncio.TimeoutError) as exc:
        print(f"  UNREACHABLE: {type(exc).__name__} — row checks skipped")
        print()
        return violations, False

    try:
        published = await conn.fetch(
            """
            SELECT id, version, label, state, published_at
            FROM institutional_profile_versions
            WHERE state IN ('approved', 'published')
            """
        )
        print(f"  institutional_profile_versions approved/published: {len(published)}")
        for row in published:
            problems = []
            if row["version"] is None:
                problems.append("missing version")
            if not (row["label"] or "").strip():
                problems.append("missing label")
            if row["state"] == "published" and row["published_at"] is None:
                problems.append("published without published_at")
            if problems:
                violations.append(
                    f"db: institutional_profile_versions {row['id']}: {', '.join(problems)}"
                )
                print(f"    VIOLATION {row['id']}: {', '.join(problems)}")

        pinned_projects = await conn.fetchrow(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE style_profile_id IS NULL) AS unmaterialised
            FROM projects
            WHERE institutional_profile_version_id IS NOT NULL
            """
        )
        print(
            f"  projects pinned to an institutional profile version: {pinned_projects['total']}"
            f" (missing materialised style_profile_id: {pinned_projects['unmaterialised']})"
        )
        if pinned_projects["unmaterialised"]:
            violations.append(
                f"db: {pinned_projects['unmaterialised']} pinned project(s) lack a "
                "materialised style_profile_id (migration 0016 trigger did not fire)"
            )

        exports = await conn.fetchrow(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE status = 'ready') AS ready,
                   count(*) FILTER (
                       WHERE status = 'ready'
                         AND (profile_version IS NULL
                              OR btrim(profile_version) = ''
                              OR profile_version = 'builtin')
                   ) AS ready_unpinned,
                   count(*) FILTER (
                       WHERE status = 'ready'
                         AND (manifest ->> 'format_profile_version') IS NULL
                   ) AS ready_no_manifest_version
            FROM exports
            """
        )
        print(
            f"  exports: total={exports['total']} ready={exports['ready']} "
            f"ready_without_profile_version={exports['ready_unpinned']} "
            f"ready_without_manifest_version={exports['ready_no_manifest_version']}"
        )
        if exports["ready_unpinned"]:
            violations.append(
                f"db: {exports['ready_unpinned']} ready export(s) have an empty or "
                "default profile_version"
            )
        if exports["ready_no_manifest_version"]:
            violations.append(
                f"db: {exports['ready_no_manifest_version']} ready export(s) lack "
                "manifest.format_profile_version"
            )

        dist = await conn.fetch(
            """
            SELECT CASE
                       WHEN profile_version LIKE 'style:%' THEN 'style:<id>:<ts>'
                       WHEN profile_version LIKE '%:v%' THEN 'governed label'
                       ELSE profile_version
                   END AS shape,
                   count(*) AS n
            FROM exports
            GROUP BY 1
            ORDER BY 2 DESC
            """
        )
        if dist:
            print("  exports.profile_version shapes: "
                  + ", ".join(f"{r['shape']}={r['n']}" for r in dist))
    finally:
        await conn.close()
    print()
    return violations, True


# ---------------------------------------------------------------------------
# Structural gaps — reported honestly, never patched here
# ---------------------------------------------------------------------------

GAPS: tuple[str, ...] = (
    "exports.profile_version is a free-text label with no FK to "
    "institutional_profile_versions; the institutional profile *id + integer "
    "version* is not persisted on the export row itself.",
    "When a project carries a StyleProfile override, "
    "app/services/export_service.py::_resolve_project_profile records "
    "'style:<style_profile_id>:<created_at>' and DROPS the governed base "
    "version label (e.g. 'mcc_ma_english_2026:v1'), so the base profile "
    "version is not recoverable from the export row alone.",
    "Institutional identity of an export is only recoverable by joining "
    "projects.institutional_profile_version_id, which is mutable after the "
    "export was rendered — not a durable per-export pin.",
    "Durable institutional pinning exists at the submission-package level "
    "(submission_packages.profile_version_id FK), not per-export.",
)


def print_gaps() -> None:
    """Print the known structural gaps in profile pinning."""
    print("== Known structural gaps (reported, not patched) ==")
    for i, gap in enumerate(GAPS, 1):
        print(f"  GAP-{i}: {gap}")
    print()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--database-url",
        default=os.environ.get("CHECK_DATABASE_URL", DEFAULT_DB_URL),
        help="PostgreSQL URL for row checks (default: local test DB on :5453).",
    )
    parser.add_argument(
        "--skip-db", action="store_true", help="Run registry/source checks only."
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Also fail on structural gaps and an unreachable database.",
    )
    args = parser.parse_args(argv)

    violations = check_registry()
    violations += check_source_wiring()

    db_reachable = True
    if args.skip_db:
        print("== Database rows == skipped (--skip-db)\n")
    else:
        db_violations, db_reachable = asyncio.run(
            check_database(normalise_db_url(args.database_url))
        )
        violations += db_violations

    print_gaps()

    if violations:
        print(f"RESULT: FAIL — {len(violations)} violation(s):")
        for v in violations:
            print(f"  - {v}")
        return 1
    if args.strict and (GAPS or not db_reachable):
        reason = "structural gaps present" if db_reachable else "database unreachable"
        print(f"RESULT: FAIL (--strict) — no row violations, but {reason}.")
        return 1
    suffix = "" if db_reachable else " (database unreachable — row checks skipped)"
    print(f"RESULT: PASS — no registry/source/row violations{suffix}. "
          f"{len(GAPS)} structural gap(s) noted above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
