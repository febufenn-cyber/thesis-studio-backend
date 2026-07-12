"""Repeatable backup-and-restore drill for the Thesis Studio Postgres database.

The drill proves, with machine-readable evidence, that a plain ``pg_dump`` of the
source database can be restored into a brand-new database with zero integrity
loss:

1. Seed a synthetic drill project into the SOURCE database using the app's own
   ORM models (institution, users, memberships, project document JSONB,
   manuscript revision, sources/quotes, snapshot, approvals, attestations,
   final exports, a sealed submission package and durable job rows).
2. Record SHA-256 checksums (canonical document, sealed-package manifest),
   a per-table row-count inventory and a local storage object inventory.
3. ``pg_dump`` the source database (docker exec preferred, host client
   binaries over TCP as an automatic fallback).
4. Restore into a NEW isolated database (default ``thesis_restore_drill``).
5. Run ``alembic current`` against the restored database.
6. Re-verify: row counts, tenant memberships, canonical document checksum,
   sealed submission checksum and a clean job-lease recovery state.
7. Measure wall-clock RTO (dump + restore + verify) and report RPO for a
   fresh dump. Drop the restore database afterwards (unless kept) and emit
   JSON evidence.

Safety: the drill refuses to touch any database whose name does not start
with ``thesis_``. It never logs thesis prose, quotations, emails or secrets —
identifiers, counts and checksums only.

Usage:
    .venv-validate/bin/python scripts/run_restore_drill.py \
        --source-db thesis_studio \
        --evidence-out docs/release/evidence/RESTORE_DRILL_LOCAL_RAW.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Bootstrap required settings BEFORE importing app modules (app.db.session
# builds an engine from Settings at import time). The app engine itself is
# never used by this script — the drill creates its own NullPool engines.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://thesis:thesis@localhost:5452/thesis_studio",
)
os.environ.setdefault("ENV", "development")
os.environ.setdefault("JWT_SECRET", "d" * 64)
os.environ.setdefault("ANTHROPIC_API_KEY", "restore-drill-placeholder")
os.environ.setdefault("DEFAULT_INSTITUTION_SHORT_NAME", "DRILL")

from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.canonical.migrations import apply_payload  # noqa: E402
from app.collaboration.sealing import create_attestation, seal_submission  # noqa: E402
from app.collaboration.workflow import canonical_checksum  # noqa: E402
from app.models.document_snapshot import DocumentSnapshot  # noqa: E402
from app.models.export import Export  # noqa: E402
from app.models.institution import Institution  # noqa: E402
from app.models.institutional_governance import SubmissionPackage  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.manuscript_revision import ManuscriptRevision  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.quote import Quote  # noqa: E402
from app.models.review_collaboration import ApprovalRecord  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.models.tenancy import OrganizationMembership, ProjectMembership  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.editor_service import create_snapshot  # noqa: E402


RESTORE_DB_DEFAULT = "thesis_restore_drill"
CONTAINER_DEFAULT = "thesis-postgres"
ENVIRONMENT_LABEL = "local-development-macos"
_DB_NAME_RE = re.compile(r"^thesis_[a-z0-9_]*$")
_HOST_PG_BIN_CANDIDATES = (
    "/opt/homebrew/opt/postgresql@16/bin",
    "/opt/homebrew/opt/libpq/bin",
    "/usr/local/opt/postgresql@16/bin",
    "/usr/local/opt/libpq/bin",
)


class DrillError(RuntimeError):
    """Raised for unrecoverable drill failures (not verification mismatches)."""


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def _sha256_json(payload: Any) -> str:
    """Return the hex SHA-256 of a canonical (sorted, compact) JSON encoding."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def package_manifest_checksum(manifest: dict) -> str:
    """Recompute a sealed-package checksum exactly as app/collaboration/sealing.py does."""
    return _sha256_json(manifest)


def assert_thesis_database(name: str) -> str:
    """Refuse any database name that does not start with ``thesis_``."""
    if not _DB_NAME_RE.match(name):
        raise DrillError(
            f"refusing to touch database {name!r}: drill only operates on databases "
            "matching ^thesis_[a-z0-9_]*$"
        )
    return name


class PgTools:
    """Runs Postgres client commands via docker exec, or host binaries over TCP."""

    def __init__(self, container: str, host: str, port: int, user: str, password: str) -> None:
        self.container = container
        self.host = host
        self.port = port
        self.user = user
        self._password = password
        self.mode = ""
        self.probe_note = ""
        self._bin_dir = ""
        self._probe()

    def _probe(self) -> None:
        """Prefer docker exec; fall back to host client binaries over TCP."""
        try:
            result = subprocess.run(
                ["docker", "exec", self.container, "pg_dump", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = None
            self.probe_note = f"docker exec probe raised {type(exc).__name__}"
        if result is not None and result.returncode == 0:
            self.mode = "docker-exec"
            self.probe_note = result.stdout.strip()
            return
        if result is not None:
            self.probe_note = (
                "docker exec unavailable: " + (result.stderr.strip() or result.stdout.strip())[:200]
            )
        for candidate in _HOST_PG_BIN_CANDIDATES:
            if (Path(candidate) / "pg_dump").exists():
                self._bin_dir = candidate
                break
        else:
            probe = subprocess.run(["which", "pg_dump"], capture_output=True, text=True)
            if probe.returncode != 0:
                raise DrillError(
                    "no usable pg_dump: docker exec failed and no host client binaries found"
                )
        self.mode = "host-client-tcp"

    def _cmd(self, tool: str, args: list[str]) -> tuple[list[str], dict[str, str]]:
        """Build the argv and env for one client tool invocation."""
        if self.mode == "docker-exec":
            return (["docker", "exec", "-i", self.container, tool, "-U", self.user, *args], {})
        binary = str(Path(self._bin_dir) / tool) if self._bin_dir else tool
        env = {**os.environ, "PGPASSWORD": self._password}
        return ([binary, "-h", self.host, "-p", str(self.port), "-U", self.user, *args], env)

    def run(
        self,
        tool: str,
        args: list[str],
        *,
        stdout_path: Path | None = None,
        stdin_path: Path | None = None,
    ) -> str:
        """Run one client tool; raise DrillError with the stderr tail on failure."""
        argv, env = self._cmd(tool, args)
        stdout_handle = stdout_path.open("wb") if stdout_path else subprocess.PIPE
        stdin_handle = stdin_path.open("rb") if stdin_path else subprocess.DEVNULL
        try:
            result = subprocess.run(
                argv,
                stdout=stdout_handle,
                stderr=subprocess.PIPE,
                stdin=stdin_handle,
                env=env or None,
                timeout=1800,
            )
        finally:
            if stdout_path:
                stdout_handle.close()  # type: ignore[union-attr]
            if stdin_path:
                stdin_handle.close()  # type: ignore[union-attr]
        if result.returncode != 0:
            stderr_tail = (result.stderr or b"").decode(errors="replace")[-600:]
            raise DrillError(f"{tool} failed (rc={result.returncode}): {stderr_tail}")
        if stdout_path is None and result.stdout is not None:
            return result.stdout.decode(errors="replace")
        return ""

    def version(self) -> str:
        """Return the pg_dump version string in the selected mode."""
        if self.mode == "docker-exec":
            argv = ["docker", "exec", self.container, "pg_dump", "--version"]
        else:
            binary = str(Path(self._bin_dir) / "pg_dump") if self._bin_dir else "pg_dump"
            argv = [binary, "--version"]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        return result.stdout.strip() or result.stderr.strip()


def _engine(url: str):
    """Create a NullPool async engine (safe across separate asyncio.run calls)."""
    return create_async_engine(url, echo=False, poolclass=NullPool)


def _session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _drill_document_payload(title: str, revision_id: UUID, source_ids: list[UUID]) -> dict:
    """Build a small but fully valid canonical schema-v3 document payload."""
    rev = str(revision_id)
    return {
        "schema_version": 3,
        "meta": {
            "doc_type": "ma_dissertation",
            "title": title,
            "candidate": {"name": "Drill Candidate", "reg_no": "DRILL-0001"},
            "degree": "Master of Arts in English",
            "department": "Department of English",
            "college": {
                "name": "Drill Synthetic College",
                "affiliation": "Drill Synthetic University",
                "city": "Drillville",
                "pin": "600000",
            },
            "guide": {"name": "Drill Supervisor", "designation": "Assistant Professor"},
            "hod": {"name": "Drill HoD", "designation": "Head of the Department"},
            "submission": {"month": "July", "year": 2026},
            "ai_disclosure": {"enabled": True, "text": "Synthetic drill disclosure.", "tools": [], "assistance_types": []},
        },
        "front_matter": [
            {
                "kind": "declaration",
                "status": "reviewed",
                "source_revision_id": rev,
                "body_blocks": [
                    {
                        "type": "paragraph",
                        "source_revision_id": rev,
                        "source_paragraph_index": 0,
                        "runs": [{"text": "Synthetic drill declaration paragraph.", "italic": False}],
                    }
                ],
            }
        ],
        "chapters": [
            {
                "number": 1,
                "title": "Synthetic Drill Chapter",
                "status": "reviewed",
                "source_revision_id": rev,
                "blocks": [
                    {
                        "type": "paragraph",
                        "source_revision_id": rev,
                        "source_paragraph_index": 1,
                        "runs": [
                            {"text": "Synthetic drill body text referencing ", "italic": False},
                            {"text": "A Synthetic Work", "italic": True},
                            {"text": ".", "italic": False},
                        ],
                    },
                    {
                        "type": "block_quote",
                        "source_revision_id": rev,
                        "source_paragraph_index": 2,
                        "text": "Synthetic drill quotation body.",
                        "citation": "(Drill 42)",
                    },
                ],
            }
        ],
        "works_cited": [{"source_id": str(source_id)} for source_id in source_ids],
    }


async def _fetch_row_counts(engine) -> dict[str, int]:
    """Count rows in every public base table, keyed by table name."""
    async with engine.connect() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name"
                )
            )
        ).scalars().all()
        counts: dict[str, int] = {}
        for table in tables:
            counts[table] = int(
                (await conn.execute(text(f'SELECT count(*) FROM "{table}"'))).scalar_one()
            )
    return counts


def _storage_inventory(storage_dir: Path) -> list[dict[str, Any]]:
    """Inventory every object under the local storage dir (path, size, sha256)."""
    objects: list[dict[str, Any]] = []
    if not storage_dir.exists():
        return objects
    for path in sorted(storage_dir.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            objects.append(
                {
                    "path": str(path.relative_to(storage_dir)),
                    "size_bytes": len(data),
                    "sha256": _sha256_bytes(data),
                }
            )
    return objects


async def seed_drill_project(source_url: str, storage_dir: Path, run_id: str) -> dict[str, Any]:
    """Seed the synthetic drill rows into the source DB and return expectations."""
    engine = _engine(source_url)
    factory = _session_factory(engine)
    try:
        async with factory() as db:
            institution = Institution(
                name=f"Drill Synthetic University {run_id}",
                short_name=f"DR{run_id[:6]}",
                slug=f"drill-{run_id}",
                email_domains="drill.invalid",
                address="1 Drill Way, Drillville",
                short_address="Drillville",
                university_name="Drill Synthetic University",
                default_department="Department of English",
                department_aided=False,
            )
            db.add(institution)
            await db.flush()

            student = User(
                email=f"drill-student-{run_id}@drill.invalid",
                full_name="Drill Student",
                institution_id=institution.id,
            )
            supervisor = User(
                email=f"drill-supervisor-{run_id}@drill.invalid",
                full_name="Drill Supervisor",
                institution_id=institution.id,
            )
            db.add_all([student, supervisor])
            await db.flush()

            db.add_all(
                [
                    OrganizationMembership(
                        institution_id=institution.id,
                        user_id=student.id,
                        role="student",
                        affiliation_status="verified",
                        status="active",
                        verified_by=supervisor.id,
                        verified_at=datetime.now(timezone.utc),
                    ),
                    OrganizationMembership(
                        institution_id=institution.id,
                        user_id=supervisor.id,
                        role="supervisor",
                        affiliation_status="verified",
                        status="active",
                    ),
                ]
            )

            project = Project(
                user_id=student.id,
                institution_id=institution.id,
                title=f"Restore Drill Synthetic Thesis {run_id}",
                meta={"title": f"Restore Drill Synthetic Thesis {run_id}"},
            )
            db.add(project)
            await db.flush()

            db.add_all(
                [
                    ProjectMembership(
                        project_id=project.id,
                        user_id=student.id,
                        role="student",
                        status="active",
                        capabilities=["document.edit", "document.export"],
                        content_access=True,
                        source_access=True,
                        ai_history_access=True,
                        granted_by=student.id,
                    ),
                    ProjectMembership(
                        project_id=project.id,
                        user_id=supervisor.id,
                        role="supervisor",
                        status="active",
                        capabilities=["review.decide", "approval.grant"],
                        content_access=True,
                        source_access=True,
                        ai_history_access=False,
                        granted_by=student.id,
                    ),
                ]
            )

            manuscript_bytes = (
                f"Synthetic drill manuscript for run {run_id}. Not real thesis content.\n"
            ).encode()
            storage_key = f"drill/{run_id}/manuscript_v1.txt"
            object_path = storage_dir / storage_key
            object_path.parent.mkdir(parents=True, exist_ok=True)
            object_path.write_bytes(manuscript_bytes)

            revision = ManuscriptRevision(
                project_id=project.id,
                user_id=student.id,
                revision_number=1,
                original_filename="drill_manuscript.txt",
                storage_key=storage_key,
                mime_type="text/plain",
                size_bytes=len(manuscript_bytes),
                checksum=_sha256_bytes(manuscript_bytes),
                parser_version="restore-drill-1",
                canonical_schema_version=3,
                canonical_snapshot={"drill": run_id},
                import_report={"paragraphs": 3, "drill": run_id},
                status="ready",
                applied=True,
                applied_at=datetime.now(timezone.utc),
            )
            db.add(revision)
            await db.flush()
            project.active_revision_id = revision.id

            source_one = Source(
                project_id=project.id,
                user_id=student.id,
                kind="book",
                fields={
                    "author": "Author, Synthetic",
                    "title": "A Synthetic Work",
                    "publisher": "Drill Press",
                    "year": "2024",
                },
                raw_entry="Author, Synthetic. A Synthetic Work. Drill Press, 2024.",
                parse_status="structured_with_review",
                import_revision_id=revision.id,
                parser_version="restore-drill-1",
                verified=True,
                verified_at=datetime.now(timezone.utc),
                verified_by=student.id,
                verification_method="drill_fixture",
            )
            source_two = Source(
                project_id=project.id,
                user_id=student.id,
                kind="journal_article",
                fields={
                    "author": "Writer, Synthetic",
                    "title": "Synthetic Findings",
                    "container": "Journal of Drills",
                    "year": "2025",
                },
                raw_entry="Writer, Synthetic. “Synthetic Findings.” Journal of Drills, 2025.",
                parse_status="structured_with_review",
                import_revision_id=revision.id,
                parser_version="restore-drill-1",
            )
            db.add_all([source_one, source_two])
            await db.flush()

            db.add_all(
                [
                    Quote(
                        source_id=source_one.id,
                        project_id=project.id,
                        user_id=student.id,
                        page_or_loc="42",
                        text="Synthetic drill quotation body.",
                        method="imported",
                        import_revision_id=revision.id,
                        source_paragraph_index=2,
                        verified=True,
                        verified_at=datetime.now(timezone.utc),
                        verified_by=student.id,
                        verification_method="drill_fixture",
                    ),
                    Quote(
                        source_id=source_two.id,
                        project_id=project.id,
                        user_id=student.id,
                        page_or_loc="7",
                        text="Second synthetic drill quotation.",
                        method="pasted",
                        import_revision_id=revision.id,
                        source_paragraph_index=3,
                    ),
                ]
            )

            apply_payload(
                project,
                _drill_document_payload(project.title, revision.id, [source_one.id, source_two.id]),
            )
            await db.commit()

            snapshot = await create_snapshot(
                db,
                project,
                student.id,
                name=f"Drill baseline v{project.document_version}",
                reason="restore_drill",
                automatic=False,
            )
            await db.commit()

            doc_checksum = canonical_checksum(project)
            for dimension, approver in (
                ("content", supervisor.id),
                ("citation", supervisor.id),
                ("formatting", supervisor.id),
                ("institutional", supervisor.id),
            ):
                db.add(
                    ApprovalRecord(
                        project_id=project.id,
                        snapshot_id=snapshot.id,
                        dimension=dimension,
                        scope_type="project",
                        decision="approved",
                        status="active",
                        approved_by=approver,
                        document_version=project.document_version,
                        document_checksum=doc_checksum,
                        note=f"Drill {dimension} approval fixture.",
                    )
                )
            await db.commit()

            await create_attestation(
                db,
                project,
                student.id,
                attestation_type="student_authorship",
                statement_version="2026.1",
                statement_text="Synthetic drill authorship attestation.",
                accepted=True,
            )
            await create_attestation(
                db,
                project,
                supervisor.id,
                attestation_type="supervisor_workflow_approval",
                statement_version="2026.1",
                statement_text="Synthetic drill supervisor attestation.",
                accepted=True,
            )

            for fmt in ("docx", "pdf"):
                artifact = f"drill artifact {fmt} {run_id}".encode()
                db.add(
                    Export(
                        project_id=project.id,
                        user_id=student.id,
                        format=fmt,
                        document_version=project.document_version,
                        manuscript_revision_id=revision.id,
                        profile_version="drill:tn_university",
                        storage_key=f"drill/{run_id}/final.{fmt}",
                        checksum=_sha256_bytes(artifact),
                        size_bytes=len(artifact),
                        status="ready",
                        report={"pass": True, "drill": run_id},
                        manifest={"state": "final", "document_version": project.document_version},
                    )
                )
            await db.commit()

            package = await seal_submission(
                db, project, supervisor.id, note="Restore drill sealed package."
            )

            job_specs = (
                ("succeeded", 1, {"ok": True, "drill": run_id}, None),
                ("queued", 0, {}, None),
                ("failed", 3, {}, "Synthetic drill failure fixture."),
            )
            for index, (status, attempts, result, error) in enumerate(job_specs):
                db.add(
                    Job(
                        kind="export_render",
                        queue_name="general",
                        project_id=project.id,
                        user_id=student.id,
                        payload={"drill": run_id, "n": index},
                        status=status,
                        attempts=attempts,
                        idempotency_key=f"restore-drill-{run_id}-{index}",
                        result=result,
                        error_message=error,
                    )
                )
            await db.commit()
            last_write_at = _utcnow_iso()

            org_rows = (
                await db.execute(
                    select(OrganizationMembership)
                    .where(OrganizationMembership.institution_id == institution.id)
                    .order_by(OrganizationMembership.user_id)
                )
            ).scalars().all()
            proj_rows = (
                await db.execute(
                    select(ProjectMembership)
                    .where(ProjectMembership.project_id == project.id)
                    .order_by(ProjectMembership.user_id)
                )
            ).scalars().all()
            membership_fingerprint = _membership_fingerprint(org_rows, proj_rows)

            jobs_by_status = dict(
                (
                    await db.execute(
                        select(Job.status, func.count(Job.id))
                        .where(Job.project_id == project.id)
                        .group_by(Job.status)
                    )
                ).all()
            )

            return {
                "run_id": run_id,
                "institution_id": str(institution.id),
                "student_id": str(student.id),
                "supervisor_id": str(supervisor.id),
                "project_id": str(project.id),
                "revision_id": str(revision.id),
                "snapshot_id": str(snapshot.id),
                "package_id": str(package.id),
                "document_version": project.document_version,
                "canonical_document_checksum": doc_checksum,
                "package_checksum": package.package_checksum,
                "package_document_checksum": package.document_checksum,
                "package_manifest_recomputed": package_manifest_checksum(package.manifest),
                "manuscript_object_key": storage_key,
                "manuscript_object_sha256": _sha256_bytes(manuscript_bytes),
                "membership_fingerprint": membership_fingerprint,
                "org_membership_count": len(org_rows),
                "project_membership_count": len(proj_rows),
                "jobs_by_status": {k: int(v) for k, v in jobs_by_status.items()},
                "source_count": 2,
                "quote_count": 2,
                "last_write_at": last_write_at,
            }
    finally:
        await engine.dispose()


def _membership_fingerprint(
    org_rows: list[OrganizationMembership], proj_rows: list[ProjectMembership]
) -> str:
    """Fingerprint tenant memberships/permissions as a canonical-JSON SHA-256."""
    payload = {
        "org": [
            {
                "id": str(row.id),
                "user_id": str(row.user_id),
                "role": row.role,
                "status": row.status,
                "affiliation_status": row.affiliation_status,
                "capability_overrides": row.capability_overrides,
            }
            for row in org_rows
        ],
        "project": [
            {
                "id": str(row.id),
                "user_id": str(row.user_id),
                "role": row.role,
                "status": row.status,
                "capabilities": row.capabilities,
                "content_access": row.content_access,
                "source_access": row.source_access,
                "ai_history_access": row.ai_history_access,
            }
            for row in proj_rows
        ],
    }
    return _sha256_json(payload)


async def _collect_baseline(source_url: str) -> dict[str, int]:
    """Row-count inventory of the source DB, taken immediately before pg_dump."""
    engine = _engine(source_url)
    try:
        return await _fetch_row_counts(engine)
    finally:
        await engine.dispose()


async def verify_restored(
    restore_url: str, expectations: dict[str, Any], baseline_counts: dict[str, int], storage_dir: Path
) -> list[dict[str, Any]]:
    """Run every post-restore verification and return a list of check results."""
    checks: list[dict[str, Any]] = []

    def check(name: str, expected: Any, actual: Any) -> None:
        checks.append(
            {"name": name, "ok": expected == actual, "expected": expected, "actual": actual}
        )

    engine = _engine(restore_url)
    factory = _session_factory(engine)
    try:
        restored_counts = await _fetch_row_counts(engine)
        check("table_count", len(baseline_counts), len(restored_counts))
        mismatched = {
            table: {"source": baseline_counts.get(table), "restored": restored_counts.get(table)}
            for table in sorted(set(baseline_counts) | set(restored_counts))
            if baseline_counts.get(table) != restored_counts.get(table)
        }
        check("row_counts_all_tables", {}, mismatched)

        async with factory() as db:
            project = (
                await db.execute(
                    select(Project).where(Project.id == UUID(expectations["project_id"]))
                )
            ).scalar_one_or_none()
            check("project_present", True, project is not None)
            if project is not None:
                check(
                    "canonical_document_checksum",
                    expectations["canonical_document_checksum"],
                    canonical_checksum(project),
                )
                check("document_version", expectations["document_version"], project.document_version)
                check("submission_locked", True, project.submission_locked)

            package = (
                await db.execute(
                    select(SubmissionPackage).where(
                        SubmissionPackage.id == UUID(expectations["package_id"])
                    )
                )
            ).scalar_one_or_none()
            check("sealed_package_present", True, package is not None)
            if package is not None:
                check("sealed_package_state", "sealed", package.state)
                check(
                    "sealed_package_checksum",
                    expectations["package_checksum"],
                    package.package_checksum,
                )
                check(
                    "sealed_package_manifest_recomputed",
                    expectations["package_checksum"],
                    package_manifest_checksum(package.manifest),
                )
                check(
                    "sealed_document_checksum",
                    expectations["package_document_checksum"],
                    package.document_checksum,
                )
                snapshot = (
                    await db.execute(
                        select(DocumentSnapshot).where(DocumentSnapshot.id == package.snapshot_id)
                    )
                ).scalar_one_or_none()
                check(
                    "sealed_snapshot_checksum",
                    package.document_checksum,
                    snapshot.checksum if snapshot else None,
                )

            org_rows = (
                await db.execute(
                    select(OrganizationMembership)
                    .where(
                        OrganizationMembership.institution_id
                        == UUID(expectations["institution_id"])
                    )
                    .order_by(OrganizationMembership.user_id)
                )
            ).scalars().all()
            proj_rows = (
                await db.execute(
                    select(ProjectMembership)
                    .where(ProjectMembership.project_id == UUID(expectations["project_id"]))
                    .order_by(ProjectMembership.user_id)
                )
            ).scalars().all()
            check(
                "membership_fingerprint",
                expectations["membership_fingerprint"],
                _membership_fingerprint(list(org_rows), list(proj_rows)),
            )
            check("org_membership_count", expectations["org_membership_count"], len(org_rows))
            check(
                "project_membership_count",
                expectations["project_membership_count"],
                len(proj_rows),
            )

            for model, name in ((Source, "source_count"), (Quote, "quote_count")):
                count = int(
                    (
                        await db.execute(
                            select(func.count(model.id)).where(
                                model.project_id == UUID(expectations["project_id"])
                            )
                        )
                    ).scalar_one()
                )
                check(name, expectations[name], count)

            revision = (
                await db.execute(
                    select(ManuscriptRevision).where(
                        ManuscriptRevision.id == UUID(expectations["revision_id"])
                    )
                )
            ).scalar_one_or_none()
            check("manuscript_revision_present", True, revision is not None)
            object_path = storage_dir / expectations["manuscript_object_key"]
            object_sha = (
                _sha256_bytes(object_path.read_bytes()) if object_path.exists() else None
            )
            check(
                "manuscript_object_checksum_matches_row",
                revision.checksum if revision else None,
                object_sha,
            )

            jobs_by_status = dict(
                (
                    await db.execute(
                        select(Job.status, func.count(Job.id))
                        .where(Job.project_id == UUID(expectations["project_id"]))
                        .group_by(Job.status)
                    )
                ).all()
            )
            check(
                "jobs_by_status",
                expectations["jobs_by_status"],
                {k: int(v) for k, v in jobs_by_status.items()},
            )
            running_total = int(
                (
                    await db.execute(select(func.count(Job.id)).where(Job.status == "running"))
                ).scalar_one()
            )
            # Same predicate as app/services/job_queue.py::_recover_expired_leases —
            # after a restore no worker holds a lease, so nothing may be 'running'.
            stale_leases = int(
                (
                    await db.execute(
                        select(func.count(Job.id)).where(
                            Job.status == "running",
                            Job.lease_expires_at.is_not(None),
                            Job.lease_expires_at <= datetime.now(timezone.utc),
                        )
                    )
                ).scalar_one()
            )
            check("jobs_running_after_restore", 0, running_total)
            check("jobs_stale_leases_recoverable", 0, stale_leases)
    finally:
        await engine.dispose()
    return checks


def _run_alembic_current(python: str, database_url: str) -> str:
    """Run ``alembic current`` against a database URL and return its stdout."""
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "JWT_SECRET": os.environ.get("JWT_SECRET", "d" * 64),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "restore-drill-placeholder"),
    }
    result = subprocess.run(
        [python, "-m", "alembic", "current"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise DrillError(f"alembic current failed: {result.stderr[-600:]}")
    return result.stdout.strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backup-and-restore drill for Thesis Studio.")
    parser.add_argument("--source-db", default="thesis_studio", help="Source database name")
    parser.add_argument("--restore-db", default=RESTORE_DB_DEFAULT, help="Restore database name")
    parser.add_argument("--evidence-out", required=True, help="Path for JSON evidence output")
    parser.add_argument(
        "--keep-restore-env",
        action="store_true",
        help="Keep the restored database and dump file for inspection",
    )
    parser.add_argument("--container", default=CONTAINER_DEFAULT, help="Postgres container name")
    parser.add_argument("--pg-host", default="localhost", help="Host for TCP fallback mode")
    parser.add_argument("--pg-port", type=int, default=5452, help="Port for TCP fallback mode")
    parser.add_argument("--pg-user", default="thesis", help="Database role")
    return parser.parse_args()


def main() -> int:
    """Run the full drill and return the process exit code."""
    args = _parse_args()
    source_db = assert_thesis_database(args.source_db)
    restore_db = assert_thesis_database(args.restore_db)
    if restore_db == source_db:
        raise DrillError("restore database must differ from the source database")

    password = os.environ.get("DRILL_PG_PASSWORD", "thesis")
    run_id = uuid4().hex[:10]
    started_at = _utcnow_iso()
    storage_dir = Path(
        os.environ.get("STORAGE_LOCAL_PATH")
        or os.environ.get("LOCAL_STORAGE_DIR")
        or (REPO_ROOT / "var" / "storage")
    )
    if not storage_dir.is_absolute():
        storage_dir = REPO_ROOT / storage_dir

    source_url = f"postgresql+asyncpg://{args.pg_user}:{password}@{args.pg_host}:{args.pg_port}/{source_db}"
    restore_url = f"postgresql+asyncpg://{args.pg_user}:{password}@{args.pg_host}:{args.pg_port}/{restore_db}"

    tools = PgTools(args.container, args.pg_host, args.pg_port, args.pg_user, password)
    print(f"[drill {run_id}] tooling mode: {tools.mode} ({tools.version()})")

    workdir = Path(tempfile.mkdtemp(prefix=f"restore_drill_{run_id}_"))
    dump_path = workdir / f"{source_db}.sql"
    timings: dict[str, float] = {}
    notes: list[str] = []
    evidence: dict[str, Any] = {
        "drill": "backup-restore",
        "schema": "robofox.restore-drill-evidence.v1",
        "environment": ENVIRONMENT_LABEL,
        "run_id": run_id,
        "started_at": started_at,
        "source": {"database": source_db, "host": args.pg_host, "port": args.pg_port},
        "restore": {"database": restore_db},
        "tooling": {"mode": tools.mode, "client_version": tools.version(), "probe_note": tools.probe_note},
        "status": "error",
    }
    exit_code = 2
    try:
        t0 = time.perf_counter()
        expectations = asyncio.run(seed_drill_project(source_url, storage_dir, run_id))
        timings["seed_seconds"] = round(time.perf_counter() - t0, 3)
        print(
            f"[drill {run_id}] seeded project {expectations['project_id']} "
            f"(package {expectations['package_id']})"
        )

        t0 = time.perf_counter()
        baseline_counts = asyncio.run(_collect_baseline(source_url))
        storage_before = _storage_inventory(storage_dir)
        timings["baseline_seconds"] = round(time.perf_counter() - t0, 3)
        print(
            f"[drill {run_id}] baseline: {len(baseline_counts)} tables, "
            f"{sum(baseline_counts.values())} rows, {len(storage_before)} storage objects"
        )

        dump_started_at = _utcnow_iso()
        t0 = time.perf_counter()
        tools.run("pg_dump", ["--no-owner", "--no-privileges", "-d", source_db], stdout_path=dump_path)
        timings["dump_seconds"] = round(time.perf_counter() - t0, 3)
        dump_bytes = dump_path.stat().st_size
        dump_sha = _sha256_bytes(dump_path.read_bytes())
        print(f"[drill {run_id}] dump complete: {dump_bytes} bytes in {timings['dump_seconds']}s")

        t0 = time.perf_counter()
        tools.run("dropdb", ["--if-exists", restore_db])
        tools.run("createdb", [restore_db])
        timings["createdb_seconds"] = round(time.perf_counter() - t0, 3)

        t0 = time.perf_counter()
        tools.run(
            "psql",
            ["-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", restore_db],
            stdin_path=dump_path,
        )
        timings["restore_seconds"] = round(time.perf_counter() - t0, 3)
        print(f"[drill {run_id}] restore complete in {timings['restore_seconds']}s")

        t0 = time.perf_counter()
        alembic_output = _run_alembic_current(sys.executable, restore_url)
        timings["alembic_current_seconds"] = round(time.perf_counter() - t0, 3)
        alembic_at_head = "(head)" in alembic_output
        print(f"[drill {run_id}] alembic current (restored): {alembic_output}")

        t0 = time.perf_counter()
        checks = asyncio.run(verify_restored(restore_url, expectations, baseline_counts, storage_dir))
        storage_after = _storage_inventory(storage_dir)
        checks.append(
            {
                "name": "storage_inventory_unchanged",
                "ok": storage_before == storage_after,
                "expected": _sha256_json(storage_before),
                "actual": _sha256_json(storage_after),
            }
        )
        checks.append(
            {
                "name": "alembic_current_at_head",
                "ok": alembic_at_head,
                "expected": "(head)",
                "actual": alembic_output,
            }
        )
        timings["verify_seconds"] = round(time.perf_counter() - t0, 3)

        rto_seconds = round(
            timings["dump_seconds"]
            + timings["createdb_seconds"]
            + timings["restore_seconds"]
            + timings["alembic_current_seconds"]
            + timings["verify_seconds"],
            3,
        )
        timings["rto_seconds"] = rto_seconds
        passed = all(item["ok"] for item in checks)

        last_write = datetime.fromisoformat(expectations["last_write_at"])
        dump_start = datetime.fromisoformat(dump_started_at)
        evidence.update(
            {
                "seed": {
                    key: expectations[key]
                    for key in (
                        "institution_id",
                        "student_id",
                        "supervisor_id",
                        "project_id",
                        "revision_id",
                        "snapshot_id",
                        "package_id",
                        "document_version",
                        "org_membership_count",
                        "project_membership_count",
                        "source_count",
                        "quote_count",
                        "jobs_by_status",
                    )
                },
                "seed_left_in_source": True,
                "checksums": {
                    "canonical_document": expectations["canonical_document_checksum"],
                    "sealed_package": expectations["package_checksum"],
                    "sealed_document": expectations["package_document_checksum"],
                    "membership_fingerprint": expectations["membership_fingerprint"],
                    "manuscript_object": expectations["manuscript_object_sha256"],
                    "dump_file": dump_sha,
                },
                "inventory": {
                    "table_count": len(baseline_counts),
                    "total_rows": sum(baseline_counts.values()),
                    "row_counts": baseline_counts,
                    "storage_dir": str(storage_dir),
                    "storage_object_count": len(storage_before),
                    "storage_objects": storage_before,
                },
                "dump": {"path": str(dump_path), "size_bytes": dump_bytes, "started_at": dump_started_at},
                "alembic_current": alembic_output,
                "verification": {"passed": passed, "checks": checks},
                "timings": timings,
                "rto": {
                    "definition": "wall-clock seconds for dump + createdb + restore + alembic check + verify",
                    "rto_seconds": rto_seconds,
                },
                "rpo": {
                    "definition": (
                        "data-loss window relative to the pg_dump snapshot; a fresh dump "
                        "captures every transaction committed before dump start"
                    ),
                    "last_committed_write_at": expectations["last_write_at"],
                    "dump_started_at": dump_started_at,
                    "write_to_dump_gap_seconds": round((dump_start - last_write).total_seconds(), 3),
                    "rpo_seconds": 0.0,
                },
                "status": "passed" if passed else "failed",
            }
        )
        exit_code = 0 if passed else 1
        failed_names = [item["name"] for item in checks if not item["ok"]]
        if failed_names:
            notes.append(f"failed checks: {failed_names}")
        print(
            f"[drill {run_id}] verification {'PASSED' if passed else 'FAILED'} "
            f"({len(checks)} checks) — RTO {rto_seconds}s, RPO 0.0s"
        )
    except DrillError as exc:
        notes.append(f"drill error: {exc}")
        print(f"[drill {run_id}] ERROR: {exc}", file=sys.stderr)
    finally:
        try:
            if args.keep_restore_env:
                notes.append(f"restore db {restore_db} and dump kept (--keep-restore-env)")
                evidence["restore"]["dropped_after"] = False
            else:
                tools.run("dropdb", ["--if-exists", restore_db])
                evidence["restore"]["dropped_after"] = True
                if exit_code == 0 and dump_path.exists():
                    dump_path.unlink()
                    notes.append("dump file removed after a passed drill")
        except DrillError as exc:
            notes.append(f"cleanup error: {exc}")
        evidence["notes"] = notes
        evidence["finished_at"] = _utcnow_iso()
        out_path = Path(args.evidence_out)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(evidence, indent=2, default=str) + "\n")
        print(f"[drill {run_id}] evidence written to {out_path}")
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DrillError as exc:
        print(f"restore drill refused/failed: {exc}", file=sys.stderr)
        sys.exit(2)
