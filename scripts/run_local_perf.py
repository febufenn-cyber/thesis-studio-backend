"""Controlled local performance benchmark for launch-readiness Subphase I.

Drives the real ASGI application in-process (httpx ASGITransport, mirroring
``tests/conftest.py``) against the local test PostgreSQL instance and measures
wall-clock latency percentiles for the project-open read, the block-level
autosave command, document search, the optimistic-concurrency conflict path,
and PostgreSQL job-queue claim throughput.

Results are explicitly local-development numbers. The in-process transport
skips the network, TLS, Nginx, and inter-host hops, so these figures bound the
application+database cost only and are NOT representative of staging SLOs.

Usage:
    DATABASE_URL=postgresql+asyncpg://thesis:thesis@localhost:5453/thesis_studio_test \
        .venv-validate/bin/python scripts/run_local_perf.py \
        --out docs/release/evidence/PERF_LOCAL_RAW.json

WARNING: this script DROPS and recreates the schema of the configured
database (like the pytest conftest does). Point it only at a scratch/test DB.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

# Allow running as ``python scripts/run_local_perf.py`` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Test/benchmark environment must be configured before importing modules that
# cache Settings (same pattern and values as tests/conftest.py).
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://thesis:thesis@localhost:5453/thesis_studio_test",
)
os.environ.setdefault("ENV", "development")
os.environ.setdefault("JWT_SECRET", "a" * 64)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-provider-key-placeholder")
os.environ.setdefault("DEFAULT_INSTITUTION_SHORT_NAME", "TU")
os.environ.setdefault("BILLING_PROVIDER", "test")
os.environ.setdefault(
    "BILLING_WEBHOOK_SECRET",
    "phase5-test-webhook-secret-at-least-32-characters",
)
os.environ.setdefault("MALWARE_SCAN_MODE", "disabled")
os.environ.setdefault("PRODUCTION_REQUIRE_MALWARE_SCAN", "false")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("LOG_LEVEL", "WARNING")
# A developer .env with DEBUG=true would turn on SQLAlchemy echo and distort
# every timing, so the benchmark pins it off unless explicitly exported.
os.environ.setdefault("DEBUG", "false")

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.canonical.model import (  # noqa: E402
    ChapterDoc,
    ParagraphBlock,
    Run,
    ThesisDocument,
)
from app.core.security import create_access_token  # noqa: E402
from app.db.session import AsyncSessionLocal, Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.institution import Institution  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.job_queue import _claim_next, enqueue_job  # noqa: E402


SEARCH_TOKEN = "hermeneutic"
JOB_KIND = "verify_project"  # mapped to the "general" queue; never dispatched here
JOB_QUEUE_NAME = "general"


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------


def percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted sample."""
    if not sorted_values:
        return float("nan")
    rank = max(1, min(len(sorted_values), round(pct / 100.0 * len(sorted_values))))
    return sorted_values[rank - 1]


def summarize(latencies_ms: list[float], errors: int, *, warmups: int, note: str | None = None) -> dict:
    """Build the per-operation stats block emitted to the raw JSON file."""
    ordered = sorted(latencies_ms)
    block: dict[str, Any] = {
        "iterations": len(latencies_ms),
        "warmups": warmups,
        "errors": errors,
        "p50_ms": round(percentile(ordered, 50), 3) if ordered else None,
        "p95_ms": round(percentile(ordered, 95), 3) if ordered else None,
        "p99_ms": round(percentile(ordered, 99), 3) if ordered else None,
        "min_ms": round(ordered[0], 3) if ordered else None,
        "max_ms": round(ordered[-1], 3) if ordered else None,
        "mean_ms": round(statistics.fmean(ordered), 3) if ordered else None,
    }
    if note:
        block["note"] = note
    return block


def rss_bytes() -> int | None:
    """Resident set size of this process (psutil if importable, else resource)."""
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except ImportError:
        pass
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # ru_maxrss is bytes on macOS and kilobytes on Linux.
        return int(peak if sys.platform == "darwin" else peak * 1024)
    except Exception:
        return None


def pool_stats() -> dict:
    """Best-effort DB pool statistics from the application engine."""
    stats: dict[str, Any] = {}
    try:
        pool = engine.pool
        stats["status"] = pool.status()
        for attr in ("size", "checkedin", "checkedout", "overflow"):
            fn = getattr(pool, attr, None)
            if callable(fn):
                stats[attr] = fn()
    except Exception as exc:  # pragma: no cover - purely informational
        stats["error"] = f"pool stats unavailable: {exc}"
    return stats


def commit_sha() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                cwd=Path(__file__).resolve().parent.parent,
            ).stdout.strip()
        )
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def build_chapters(block_count: int, chapter_count: int = 10) -> list[dict]:
    """Paragraph-only chapters totalling ``block_count`` blocks, a few runs each."""
    chapters: list[ChapterDoc] = []
    per_chapter = block_count // chapter_count
    remainder = block_count % chapter_count
    block_index = 0
    for number in range(1, chapter_count + 1):
        blocks = []
        chapter_blocks = per_chapter + (1 if number <= remainder else 0)
        for _ in range(chapter_blocks):
            token = SEARCH_TOKEN if block_index % 10 == 0 else "narrative"
            blocks.append(
                ParagraphBlock(
                    runs=[
                        Run(text=f"Paragraph {block_index} examines the {token} tradition "),
                        Run(text="in the corpus of the novel ", italic=True),
                        Run(
                            text=(
                                "and situates the argument within the wider critical "
                                "conversation on colonial modernity and form."
                            )
                        ),
                    ]
                )
            )
            block_index += 1
        chapters.append(
            ChapterDoc(
                number=number,
                title=f"Chapter {number}: Readings in Context",
                status="in_progress",
                blocks=blocks,
            )
        )
    return [chapter.model_dump(mode="json") for chapter in chapters]


async def reset_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def seed_user() -> tuple[UUID, str]:
    """Create institution + user; return (user_id, auth cookie token)."""
    async with AsyncSessionLocal() as db:
        inst = Institution(
            name="Perf Test University",
            short_name="TU",
            email_domains="test.edu",
            address="123 Test St, Testville",
            short_address="Testville",
            university_name="Perf Test University",
            default_department="Department of English",
            department_aided=False,
        )
        db.add(inst)
        await db.flush()
        user = User(
            email=f"perf-{uuid4().hex[:8]}@test.edu",
            full_name="Perf Harness",
            institution_id=inst.id,
        )
        db.add(user)
        await db.commit()
        return user.id, create_access_token(user.id)


async def seed_project(user_id: UUID, block_count: int) -> tuple[UUID, UUID]:
    """Direct ORM write of the canonical document JSONB (seeding only).

    Returns (project_id, block_id of a mid-document paragraph used for saves).
    """
    chapters = build_chapters(block_count)
    # Validate the seeded payload against the canonical model before writing.
    ThesisDocument.model_validate({"schema_version": 3, "chapters": chapters})
    middle_chapter = chapters[len(chapters) // 2]
    target_block_id = UUID(middle_chapter["blocks"][len(middle_chapter["blocks"]) // 2]["id"])
    async with AsyncSessionLocal() as db:
        project = Project(
            user_id=user_id,
            title=f"Perf Project {block_count} blocks",
            mode="operator",
            doc_type="ma_dissertation",
            format_profile="tn_university",
            document_version=1,
            canonical_schema_version=3,
            chapters=chapters,
        )
        db.add(project)
        await db.commit()
        return project.id, target_block_id


# ---------------------------------------------------------------------------
# Benchmark phases
# ---------------------------------------------------------------------------


async def timed_request(client: AsyncClient, method: str, url: str, **kwargs) -> tuple[float, Any]:
    start = time.perf_counter()
    response = await client.request(method, url, **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return elapsed_ms, response


async def bench_project_open(
    client: AsyncClient, project_id: UUID, iterations: int, warmups: int, failures: list[str]
) -> dict:
    """GET /projects/{id} — canonical document read (meta + chapters JSONB)."""
    latencies: list[float] = []
    errors = 0
    for i in range(warmups + iterations):
        elapsed, response = await timed_request(client, "GET", f"/projects/{project_id}")
        if response.status_code != 200:
            errors += 1
            failures.append(
                f"GET /projects/{project_id} iteration {i}: HTTP {response.status_code} {response.text[:200]}"
            )
            continue
        if i >= warmups:
            latencies.append(elapsed)
    return summarize(latencies, errors, warmups=warmups)


async def bench_search(
    client: AsyncClient, project_id: UUID, iterations: int, warmups: int, failures: list[str]
) -> dict:
    """GET /projects/{id}/editor/search — full-document scan search."""
    latencies: list[float] = []
    errors = 0
    total_results: int | None = None
    for i in range(warmups + iterations):
        elapsed, response = await timed_request(
            client,
            "GET",
            f"/projects/{project_id}/editor/search",
            params={"q": SEARCH_TOKEN, "limit": 100},
        )
        if response.status_code != 200:
            errors += 1
            failures.append(
                f"GET /projects/{project_id}/editor/search iteration {i}: "
                f"HTTP {response.status_code} {response.text[:200]}"
            )
            continue
        total_results = response.json().get("total")
        if i >= warmups:
            latencies.append(elapsed)
    stats = summarize(latencies, errors, warmups=warmups)
    stats["matched_results"] = total_results
    return stats


async def bench_single_block_save(
    client: AsyncClient,
    project_id: UUID,
    block_id: UUID,
    document_version: int,
    iterations: int,
    warmups: int,
    failures: list[str],
) -> tuple[dict, int]:
    """POST /projects/{id}/editor/commands update_block_text — the real autosave path.

    Each successful save increments document_version; returns final version.
    """
    latencies: list[float] = []
    errors = 0
    version = document_version
    for i in range(warmups + iterations):
        body = {
            "command_type": "update_block_text",
            "payload": {
                "block_id": str(block_id),
                "runs": [
                    {"text": f"Autosave revision {i} refines the {SEARCH_TOKEN} argument "},
                    {"text": "with a sharpened close reading ", "italic": True},
                    {"text": "of the passage under discussion."},
                ],
            },
            "expected_document_version": version,
        }
        elapsed, response = await timed_request(
            client, "POST", f"/projects/{project_id}/editor/commands", json=body
        )
        if response.status_code != 200:
            errors += 1
            failures.append(
                f"POST /projects/{project_id}/editor/commands iteration {i}: "
                f"HTTP {response.status_code} {response.text[:200]}"
            )
            # Resynchronise the version token so one failure doesn't cascade.
            refetch = await client.get(f"/projects/{project_id}")
            if refetch.status_code == 200:
                version = refetch.json()["document_version"]
            continue
        version = response.json()["document_version"]
        if i >= warmups:
            latencies.append(elapsed)
    note = (
        "Full canonical-document rewrite per save (whole-JSONB persistence, command + event rows); "
        "includes any periodic auto-snapshot that falls inside the measured window "
        "(AUTO_SNAPSHOT_EVERY=25 versions)."
    )
    return summarize(latencies, errors, warmups=warmups, note=note), version


async def bench_conflict_path(
    client: AsyncClient,
    project_id: UUID,
    block_id: UUID,
    current_version: int,
    iterations: int,
    warmups: int,
    failures: list[str],
) -> tuple[dict, dict, int]:
    """Optimistic concurrency: stale-save 409 latency + a truly concurrent pair.

    Returns (stale_409_stats, concurrent_outcome, final_document_version).
    """

    def save_body(expected: int, tag: str) -> dict:
        return {
            "command_type": "update_block_text",
            "payload": {
                "block_id": str(block_id),
                "runs": [{"text": f"Conflict probe {tag} against version {expected}."}],
            },
            "expected_document_version": expected,
        }

    # Part 1: deterministic stale writes (same base version repeatedly -> 409).
    # current_version - 1 is guaranteed stale and never mutates the document.
    latencies: list[float] = []
    errors = 0
    stale_version = current_version - 1
    for i in range(warmups + iterations):
        elapsed, response = await timed_request(
            client,
            "POST",
            f"/projects/{project_id}/editor/commands",
            json=save_body(stale_version, f"stale-{i}"),
        )
        if response.status_code != 409:
            errors += 1
            failures.append(
                f"conflict stale-save iteration {i}: expected HTTP 409, got "
                f"{response.status_code} {response.text[:200]}"
            )
            continue
        if i >= warmups:
            latencies.append(elapsed)
    stale_stats = summarize(
        latencies,
        errors,
        warmups=warmups,
        note="Stale expected_document_version rejected with 409; no document mutation.",
    )

    # Part 2: two interleaved saves sharing the same base version, in flight
    # concurrently through the ASGI app. Exactly one should win.
    async def one(tag: str) -> tuple[str, int, float]:
        elapsed, response = await timed_request(
            client,
            "POST",
            f"/projects/{project_id}/editor/commands",
            json=save_body(current_version, tag),
        )
        return tag, response.status_code, elapsed

    results = await asyncio.gather(one("A"), one("B"))
    statuses = sorted(status for _, status, _ in results)
    outcome = {
        "base_version": current_version,
        "responses": [
            {"request": tag, "status": status, "latency_ms": round(elapsed, 3)}
            for tag, status, elapsed in results
        ],
        "one_won_one_409": statuses == [200, 409],
    }
    if statuses != [200, 409]:
        failures.append(
            f"concurrent same-base-version saves returned statuses {statuses} "
            "(expected exactly one 200 and one 409)"
        )
    final_version = current_version + statuses.count(200)
    # Confirm the version the server actually reached.
    refetch = await client.get(f"/projects/{project_id}")
    if refetch.status_code == 200:
        final_version = refetch.json()["document_version"]
    return stale_stats, outcome, final_version


async def queue_depth(db, status: str | None = None) -> int:
    query = select(func.count(Job.id)).where(Job.queue_name == JOB_QUEUE_NAME)
    if status:
        query = query.where(Job.status == status)
    return int((await db.execute(query)).scalar_one())


async def bench_job_queue(user_id: UUID, job_count: int, failures: list[str]) -> dict:
    """Enqueue verify_project jobs and measure worker-loop claim throughput.

    Jobs are claimed exactly the way ``worker_loop`` claims them (one
    ``_claim_next`` FOR UPDATE SKIP LOCKED pass per job) but are never
    dispatched: ``verify_project`` has no dispatch arm and this benchmark must
    not run AI/PDF work. Claimed rows are deleted during cleanup.
    """
    result: dict[str, Any] = {"job_kind": JOB_KIND, "queue": JOB_QUEUE_NAME, "jobs": job_count}

    async with AsyncSessionLocal() as db:
        result["queue_depth_before_enqueue"] = await queue_depth(db, "queued")

        enqueue_start = time.perf_counter()
        job_ids: list[UUID] = []
        for i in range(job_count):
            job = await enqueue_job(
                db,
                kind=JOB_KIND,
                user_id=user_id,
                project_id=None,
                payload={"perf_probe": i},
            )
            job_ids.append(job.id)
        await db.commit()
        result["enqueue_total_ms"] = round((time.perf_counter() - enqueue_start) * 1000.0, 3)
        result["enqueue_jobs_per_second"] = round(
            job_count / ((time.perf_counter() - enqueue_start) or 1e-9), 1
        )

        result["queue_depth_after_enqueue"] = await queue_depth(db, "queued")

        # Oldest-job age: the scale-trigger metric (min(created_at) over queued).
        age_latencies: list[float] = []
        oldest_age_seconds: float | None = None
        for _ in range(10):
            start = time.perf_counter()
            oldest = (
                await db.execute(
                    select(func.min(Job.created_at)).where(
                        Job.status == "queued", Job.queue_name == JOB_QUEUE_NAME
                    )
                )
            ).scalar_one_or_none()
            age_latencies.append((time.perf_counter() - start) * 1000.0)
            if oldest is not None:
                oldest_age_seconds = max(
                    0.0, (datetime.now(timezone.utc) - oldest).total_seconds()
                )
        result["oldest_job_age_seconds_at_measurement"] = (
            round(oldest_age_seconds, 3) if oldest_age_seconds is not None else None
        )
        result["oldest_job_age_query"] = summarize(age_latencies, 0, warmups=0)

    # Claim loop: one pass per job, identical to worker_loop's claim step.
    worker_id = "perf-harness:claim-bench"
    claim_latencies: list[float] = []
    claimed = 0
    claim_start = time.perf_counter()
    while True:
        start = time.perf_counter()
        job_id = await _claim_next(worker_id, {JOB_QUEUE_NAME})
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if job_id is None:
            break
        claim_latencies.append(elapsed_ms)
        claimed += 1
        if claimed > job_count:
            failures.append("job queue claim loop claimed more jobs than were enqueued")
            break
    claim_total_s = time.perf_counter() - claim_start
    if claimed != job_count:
        failures.append(f"job queue: enqueued {job_count} jobs but claimed {claimed}")
    result["claimed_jobs"] = claimed
    result["claim_total_seconds"] = round(claim_total_s, 3)
    result["claim_throughput_jobs_per_second"] = (
        round(claimed / claim_total_s, 1) if claim_total_s > 0 else None
    )
    result["claim_latency"] = summarize(
        claim_latencies,
        0,
        warmups=0,
        note=(
            "Per-pass latency of _claim_next (lease sweep + deadline sweep + "
            "FOR UPDATE SKIP LOCKED claim + commit), single worker."
        ),
    )

    async with AsyncSessionLocal() as db:
        result["queue_depth_after_claims_queued"] = await queue_depth(db, "queued")
        result["queue_depth_after_claims_running"] = await queue_depth(db, "running")
        # Cleanup: remove the probe jobs so the scratch queue is left empty.
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()
        result["cleanup"] = "probe jobs deleted"
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run_benchmark(args: argparse.Namespace) -> dict:
    failures: list[str] = []
    report: dict[str, Any] = {
        "metadata": {
            "commit_sha": commit_sha(),
            "environment": (
                "local-development-macos (M-series, in-process ASGI, "
                "results NOT representative of staging SLOs)"
            ),
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "database_url_host": os.environ["DATABASE_URL"].rsplit("@", 1)[-1],
            "iterations_per_operation": args.iterations,
            "warmups_per_operation": args.warmups,
            "transport": "httpx ASGITransport (in-process, no network/TLS/proxy)",
        },
        "process": {"rss_bytes_start": rss_bytes()},
        "operations": {},
        "failures": failures,
    }

    print("Resetting schema on scratch database ...")
    await reset_schema()
    user_id, token = await seed_user()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"access_token": token},
        timeout=120.0,
    ) as client:
        sanity = await client.get("/projects")
        if sanity.status_code != 200:
            raise RuntimeError(
                f"Auth sanity check failed: GET /projects -> {sanity.status_code} {sanity.text[:300]}"
            )

        for block_count in args.sizes:
            print(f"Seeding project with {block_count} blocks ...")
            project_id, block_id = await seed_project(user_id, block_count)
            size_key = f"{block_count}_blocks"
            ops: dict[str, Any] = {"project_id": str(project_id)}

            print(f"  [{size_key}] project open (GET /projects/{{id}}) ...")
            ops["project_open_get_canonical_document"] = await bench_project_open(
                client, project_id, args.iterations, args.warmups, failures
            )

            print(f"  [{size_key}] search (GET /projects/{{id}}/editor/search) ...")
            ops["search_editor_document"] = await bench_search(
                client, project_id, args.iterations, args.warmups, failures
            )

            print(f"  [{size_key}] single-block save (POST /projects/{{id}}/editor/commands) ...")
            save_stats, version = await bench_single_block_save(
                client, project_id, block_id, 1, args.iterations, args.warmups, failures
            )
            ops["single_block_save_update_block_text"] = save_stats

            print(f"  [{size_key}] optimistic concurrency conflict path ...")
            stale_stats, concurrent_outcome, version = await bench_conflict_path(
                client, project_id, block_id, version, args.iterations, args.warmups, failures
            )
            ops["optimistic_concurrency_stale_save_409"] = stale_stats
            ops["optimistic_concurrency_interleaved_pair"] = concurrent_outcome
            ops["final_document_version"] = version

            report["operations"][size_key] = ops

        report["process"]["rss_bytes_after_http_benchmarks"] = rss_bytes()

        print(f"Job queue benchmark: enqueue + claim {args.jobs} '{JOB_KIND}' jobs ...")
        report["operations"]["job_queue"] = await bench_job_queue(user_id, args.jobs, failures)

    report["process"]["rss_bytes_end"] = rss_bytes()
    report["process"]["db_pool"] = pool_stats()
    await engine.dispose()
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/release/evidence/PERF_LOCAL_RAW.json"),
        help="Path for the raw JSON results file.",
    )
    parser.add_argument("--iterations", type=int, default=30, help="Measured iterations per op.")
    parser.add_argument("--warmups", type=int, default=3, help="Warmup iterations per op.")
    parser.add_argument("--jobs", type=int, default=200, help="Jobs to enqueue for the queue bench.")
    parser.add_argument(
        "--sizes",
        type=lambda raw: [int(part) for part in raw.split(",")],
        default=[500, 2000, 5000],
        help="Comma-separated block counts to seed (default 500,2000,5000).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = asyncio.run(run_benchmark(args))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nWrote {args.out}")
    if report["failures"]:
        print(f"{len(report['failures'])} failure(s) recorded:")
        for failure in report["failures"]:
            print(f"  - {failure}")
    else:
        print("No failures recorded.")


if __name__ == "__main__":
    main()
