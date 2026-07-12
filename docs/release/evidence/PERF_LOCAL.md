# Local Performance Benchmark — Subphase I (Controlled, Local Only)

- **Raw data:** `docs/release/evidence/PERF_LOCAL_RAW.json`
- **Harness:** `scripts/run_local_perf.py` (in-process httpx `ASGITransport`, real routers, real per-request DB sessions and commits, seeded user + auth cookie)
- **Commit:** `81c9b6ad841bfdc427565099df9de0ca617e3c33`
- **Environment:** local-development-macos (M-series, in-process ASGI, results NOT representative of staging SLOs); Python 3.11.14; PostgreSQL 16.14 (Dockerised, `localhost:5453`, scratch test database)
- **Method:** 3 warmups then 30 measured iterations per operation, wall-clock (`time.perf_counter`), nearest-rank percentiles. Zero HTTP errors across all measured read/save/search/conflict iterations.

Seeded canonical documents are paragraph-only blocks with 3 runs each (~402 bytes/block as JSON): 500 blocks ≈ 0.19 MiB, 2000 ≈ 0.77 MiB, 5000 ≈ 1.92 MiB.

## Measured results

| Operation | Endpoint | 500 blocks p50 / p95 / p99 (ms) | 2000 blocks p50 / p95 / p99 (ms) | 5000 blocks p50 / p95 / p99 (ms) | Errors |
|---|---|---|---|---|---|
| Project open (canonical document read) | `GET /projects/{id}` | 4.3 / 5.1 / 38.9 | 9.4 / 10.0 / 44.1 | 18.8 / 53.8 / 55.8 | 0 |
| Single-block save (autosave path) | `POST /projects/{id}/editor/commands` (`update_block_text`) | 44.6 / 70.7 / 78.5 | 195.0 / 223.9 / 229.4 | 502.3 / 541.2 / 627.9 | 0 |
| Document search (present) | `GET /projects/{id}/editor/search?q=…` | 9.7 / 43.4 / 45.6 | 66.1 / 68.6 / 107.0 | 145.9 / 162.5 / 170.4 | 0 |
| Stale-save conflict (409 path) | same save endpoint, stale `expected_document_version` | 4.4 / 4.7 / 4.7 | 8.3 / 8.8 / 42.9 | 17.0 / 53.0 / 55.4 | 0 |

Search endpoint status: **present** (`/projects/{id}/editor/search`, substring scan over the canonical document in Python). It matched 50/100/100 results at the three sizes (capped at `limit=100`).

The p99≈max spikes on otherwise tight distributions (e.g. 38.9 ms on a 4.3 ms p50) are single-sample outliers over 30 iterations — connection pool warm-up / GC on the shared event loop, visible because n=30.

### Job queue (PostgreSQL, `verify_project` kind, `general` queue, single worker)

| Metric | Value |
|---|---|
| Jobs enqueued | 200 (never dispatched — no AI/PDF work run) |
| Enqueue throughput | ~2,135 jobs/s (93.7 ms total, one commit) |
| Queue depth before → after enqueue | 0 → 200 |
| Oldest-job age at measurement | 0.063 s (freshly enqueued) |
| Oldest-job age query (`min(created_at)` over queued) | p50 0.48 ms, p95 1.28 ms |
| Claim throughput (one `_claim_next` pass per job, `FOR UPDATE SKIP LOCKED`) | **323 jobs/s** for one worker |
| Per-claim latency (incl. lease + deadline sweeps + commit) | p50 3.1 ms, p95 3.7 ms, p99 4.0 ms |
| Queue depth after claims | 0 queued / 200 running (probe rows then deleted) |

### Process / pool

| Metric | Value |
|---|---|
| Peak RSS at start / end (`resource.ru_maxrss`, macOS bytes) | 140.0 MiB → 289.4 MiB |
| DB pool (app engine, pool_size=10, max_overflow=20) | max 2 connections ever checked out; 0 checked out at exit; no overflow |

## Finding: optimistic-concurrency lost-update window under true concurrency

The **sequential** conflict path works exactly as designed: a save carrying a stale `expected_document_version` is rejected with **409** in single-digit-to-low-double-digit milliseconds and never mutates the document (30/30 iterations at every size).

However, the benchmark's required assertion — *two interleaved saves with the same base version yield exactly one 409* — **failed at all three document sizes**. Two saves fired concurrently (`asyncio.gather`) with the same `expected_document_version` both returned **200**, and the document version advanced by only 1 (base 34 → final 35). The version check in `app/services/editor_service.py::_apply` is an application-level read-then-write: both requests read version 34 before either committed, both passed the check, and the second commit silently overwrote the first (last-writer-wins; the first save's content is lost while its client believes it succeeded). Reproduced 3/3 times in the official run; recorded verbatim in the raw JSON `failures` array and per-size `optimistic_concurrency_interleaved_pair` blocks. It is a timing race, not deterministic: a separate smoke run at 200 blocks produced the correct [200, 409], and the window widens with document size because the whole-document validate-and-rewrite lengthens the span between version check and commit.

Exposure today is limited (single-user-per-project autosave, single event loop serialises most interleavings), but with two web instances (production topology requirement #6) or a double-firing client this becomes a real silent-data-loss path. Suggested fix direction before staging load tests: enforce the version at the database (e.g. `UPDATE projects SET document_version = :v+1 … WHERE id = :id AND document_version = :v` and 409 on rowcount 0, or `SELECT … FOR UPDATE` on the project row for the check-apply-commit span). Not fixed in this subphase — measurement only.

## Caveats (read before quoting any number)

- **In-process ASGI transport**: no TCP, no TLS, no Nginx/Cloudflare hop, no HTTP parsing over a socket. Real client latency adds network RTT + proxy + TLS on top of everything above.
- **Single host, zero background load**: app, benchmark driver and PostgreSQL share one laptop. No concurrent users except the deliberate 2-request conflict probe; latencies are best-case single-tenant numbers.
- **Dockerised scratch PostgreSQL** on the same machine (Docker Desktop VM disk — effectively memory-cached, unlike the production DB host with real fsync and network between app and DB).
- **M-series development hardware**, not the 956 MB Oracle VM production target — absolute numbers do not transfer; scaling *shape* (how cost grows with document size) does.
- Save percentiles include one periodic auto-snapshot (`AUTO_SNAPSHOT_EVERY=25`) falling inside each 33-save window — this is real autosave behaviour, kept in.
- RSS is peak (`ru_maxrss`), monotonic; end-of-run equals post-HTTP peak.

## Capacity recommendations vs. SLO starting points (docs/phase5/production-topology.md)

| SLO starting point | Locally assessable? | Local evidence | Recommendation |
|---|---|---|---|
| Canonical document saves: 99.9% successful / 30 days | **No** (success-rate SLO needs production volume, real infra failures, and time) | 99/99 measured saves succeeded; latency, not success, is the local signal | Track save success-rate from `events`/command rows in staging. **Fix the lost-update window first** — a silently overwritten save is a failed save the SLO cannot see. |
| Project reads: p95 < 500 ms | **Partially** (application+DB cost only) | Worst local read p95 = 53.8 ms at 5000 blocks — ~9× headroom before any network/proxy cost | Read path is not the near-term bottleneck. Budget ~100–150 ms for network/TLS/proxy in staging; re-verify at 5000 blocks under 25/50/100 concurrent users. |
| DOCX exports: 95% < 2 min | **No** — not exercised (this benchmark deliberately runs no export/PDF/AI jobs) | Claim overhead is negligible: 3.1 ms p50 per claim, 323 claims/s per worker → render time will dominate end-to-end export latency | Assess on staging with the PDF/general workers and LibreOffice installed. |
| PDF exports / AI availability / upload safety | **No** (separate components, not exercised) | — | Staging-only. |

**Save-latency capacity insight (the real local finding):** single-block autosave cost scales with total document size, not edit size — p50 goes 45 → 195 → 502 ms across 0.19 → 0.77 → 1.92 MiB documents (near-linear, ~260 ms per MiB on this hardware) because every save re-validates and rewrites the whole canonical JSONB plus command/event rows. On production hardware expect materially worse. Before onboarding theses beyond ~5000 blocks, either accept ~0.5–1 s autosaves, debounce client saves, or move to per-chapter persistence (already the M5 direction). A single async worker process can sustain at most ~2 large-document saves/second; this, not reads, should drive web-instance count.

### Concrete scale-trigger metrics

Queue counts and oldest-job age per queue/status are already exposed by the API — via `GET /institutions/{institution_id}/reliability/dashboard` (`queues[].count`, `queues[].oldest_age_seconds`); the public `/status` endpoint exposes component states and active incidents, not queue numbers, so wire the dashboard (or an equivalent internal scrape of the `jobs` table) into monitoring. Suggested triggers:

- **Queue depth**: `general` queue `queued` count > 50 sustained 5 min → add a general worker; `pdf` queue > 10 sustained → add a PDF worker (matches topology's "oldest PDF job" trigger).
- **Oldest-job age** (`oldest_age_seconds` for `status=queued`): > 60 s on `general`, > 120 s on `pdf` → scale that worker pool. The metric costs < 1.3 ms p95 to compute, so poll freely.
- **DB pool saturation**: alert when checked-out connections ≥ 8/10 (80% of `pool_size`) sustained, or any overflow use sustained > 5 min → investigate slow queries before raising pool size. (Local run never exceeded 2.)
- **Worker heartbeat lag**: `jobs.heartbeat_at` older than 60 s (3 × `JOB_HEARTBEAT_SECONDS=20`) on a `running` job → worker presumed stuck; lease expiry (`JOB_LEASE_SECONDS=120`) will requeue, but alert at heartbeat lag rather than waiting for the lease.
- **Claim overhead is not a trigger**: at 323 claims/s per worker, claiming saturates far above any realistic job arrival rate; watch job *runtime* and the two metrics above instead.

### Staging load tests: 25 / 50 / 100 concurrent users

**Blocked — no staging environment exists.** These runs require the production topology (two web instances behind health-aware routing, isolated PostgreSQL, real workers) per `docs/phase5/STAGING_BLOCKERS.md` and cannot be substituted by this local benchmark.
