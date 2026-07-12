# Robofox Thesis Studio — Production Topology

## Goal

Reduce the blast radius of application, AI, PDF, database, storage, upload-safety and deployment failures without introducing premature microservices.

## Logical topology

```text
Cloudflare / health-aware reverse proxy
        |
        +-- web-a (FastAPI)
        +-- web-b (FastAPI)
                |
                +-- isolated PostgreSQL
                +-- Cloudflare R2
                +-- internal ClamAV
                +-- PostgreSQL job queue
                       +-- general worker
                       +-- AI worker
                       +-- PDF worker
                       +-- maintenance worker
```

The codebase remains a modular monolith. Runtime processes are separate failure and capacity domains.

## Required production boundaries

1. PostgreSQL must not run on the application host.
2. `STORAGE_BACKEND=r2`; local storage fallback is rejected in production.
3. PDF conversion runs only on the PDF worker queue.
4. AI execution runs only on the AI worker queue and has independent provider health.
5. Thesis Studio must not share a host with unrelated Robofox production applications.
6. At least two application instances sit behind health-aware routing before uptime commitments.
7. Workers use expiring leases and idempotent operation identifiers.
8. Secrets are injected through the deployment environment or mounted secret files.
9. Manuscript uploads pass through a private, health-checked ClamAV service before DOCX parsing.
10. Both application and ClamAV images are pinned to immutable references.
11. The deployed SHA is reachable from `main` and has `release-candidates/<sha>.json` validation evidence.

If ClamAV is unavailable, new uploads fail with 503 while existing editing, review and export workflows remain available.

## Durable versus rebuildable storage

| Prefix / class | Durability | Retention authority |
|---|---:|---|
| `originals/` | Durable | Contract and institution policy |
| `revisions/` | Durable | Contract and institution policy |
| `sealed/` | Durable | Submission/contract policy; deletion may require institution approval |
| `exports/` | Mixed | Final/sealed exports durable; draft exports policy-driven |
| `previews/` | Rebuildable | Short lifecycle |
| `temp/` | Rebuildable | Automatic expiry |
| incomplete multipart uploads | Rebuildable | Automatic cleanup |
| ClamAV signature database | Rebuildable | Vendor update lifecycle |

Lifecycle rules must be prefix-scoped and tested against an inventory snapshot before publication.

## Internal SLO starting points

These are internal objectives, not customer SLAs:

- Canonical document saves: 99.9% successful over 30 days.
- Project reads: p95 below 500 ms.
- DOCX exports: 95% complete within two minutes when the queue is healthy.
- PDF exports: measured separately from editing availability.
- AI availability: measured separately from the application.
- Upload-safety availability: measured separately; scanner outage blocks uploads only.
- Restore drills: database RTO target 120 minutes; RPO target 15 minutes.
- Acknowledged cross-tenant disclosure: zero tolerance and SEV-1.

External commitments require observed history and contractual review.

## Scaling thresholds

Add web capacity when measured CPU, latency or deployment downtime breaches the internal objective. Add PDF workers when the oldest PDF job or memory pressure breaches objective. Add ClamAV capacity when scan latency or queueing breaches the upload objective. Add read replicas only when verified database reads are the bottleneck. Add specialist search only after PostgreSQL search fails measured needs. Split a module into a service only for independent scaling, security isolation, deployment isolation or clear team ownership.

## Release identity

Every running process receives:

- `RELEASE_SHA`
- `BUILD_TIME`
- `SCHEMA_VERSION`
- `RENDERER_VERSION`
- `PROMPT_BUNDLE_VERSION`
- `CANONICAL_SCHEMA_VERSION`

Exports and jobs retain version/checksum context so a final output can be investigated and reproduced. The release workflow also requires durable validation evidence for the exact implementation SHA before an image is pushed.
