# Phase 1 — Trusted Manuscript Conversion

Phase 1 converts an uploaded `.docx` manuscript into a governed canonical thesis document without silently changing or discarding academic content.

It is intentionally conservative. Ambiguous structure, unsupported Word objects, uncertain citations, unverified sources, and unverified quotations become visible review findings. They do not become invented data.

## Trust invariants

1. **The original upload is immutable.** Every upload is stored as a new `ManuscriptRevision` with filename, byte size, SHA-256 checksum, parser version, schema version, and revision lineage.
2. **Canonical locations are stable.** Chapters, front-matter entries, and blocks have UUIDs. Imported content retains the source revision and original paragraph index.
3. **Unsupported content is never silently dropped.** DOCX preflight reports tables, drawings, equations, comments, footnotes/endnotes, tracked changes, embedded objects, and package anomalies.
4. **Citation matching is conservative.** Same-surname ambiguity is blocking. A human decision is stored for the exact block UUID and raw citation occurrence.
5. **Verification is revision-isolated.** Only manual registry entries plus records imported from the active manuscript revision may satisfy the current document.
6. **Canonical writes are version-aware.** The trusted UI sends `expected_version`; stale writes return HTTP 409.
7. **Final exports are deterministic and gated.** They require a passing verifier report and authorship/citation responsibility acknowledgement.
8. **Review exports are not final exports.** They may retain visible review markers, but the manifest state is `review` and downloads are prefixed `REVIEW_`.
9. **Every export is bound to one state.** It records the document version, manuscript revision, format-profile version, source/quotation counts, output checksum, and post-render QA.
10. **Heavy work is durable.** Ingestion and exports run through PostgreSQL jobs claimed with `FOR UPDATE SKIP LOCKED`; retries are idempotent.

## Operator workflow

### 1. Create a project

`POST /projects`

Choose a document type and governed format profile. The trusted workspace currently exposes:

- `mcc_ma_english_2026` — versioned MCC MA English profile with 1.5 line spacing and native Word TOC.
- `tn_university` — generic, explicitly non-institution-certified fallback.
- `mla_strict` — MLA-oriented profile.

### 2. Upload a manuscript

`POST /projects/{project_id}/manuscript`

Multipart fields:

- `file`: `.docx`, maximum 25 MB.
- `apply_when_ready`: apply the parsed revision automatically when ingestion succeeds.
- `force_duplicate`: allow a byte-identical upload when an intentional duplicate revision is required.

The request streams to disk, calculates SHA-256, validates the DOCX ZIP package, stores the original, creates an immutable revision, and enqueues `ingest_manuscript`.

### 3. Follow durable job status

- `GET /projects/{project_id}/jobs`
- `GET /projects/{project_id}/revisions`

Job states: `queued`, `running`, `succeeded`, `failed`.

Revision states: `queued`, `processing`, `ready`, `failed`.

A worker retry is a no-op when the durable result already exists.

### 4. Review preservation and import findings

The revision `import_report` includes:

- DOCX preflight counts and evidence.
- chapter/front-matter parsing notes.
- in-text citation occurrences and candidates.
- quotation linkage results.
- paragraph preservation accounting.
- stable issue IDs and blocking counts.

Resolve an import issue with:

`POST /projects/{project_id}/revisions/{revision_id}/issues/{issue_id}/resolve`

The request requires `expected_version` and a human resolution note.

### 5. Resolve exact citation occurrences

`POST /projects/{project_id}/citation-resolutions`

A resolution records:

- revision ID;
- stable block UUID;
- exact raw citation text;
- selected source UUID;
- operator identity and timestamp.

For a block/verse quotation, the same transaction can create and attach the quotation registry record.

### 6. Verify sources and quotations

Sources preserve the raw bibliography entry, parser status/confidence, identifiers, import revision, and verification actor/time.

Quotations preserve exact text, location, evidence snapshot, import revision, and verification actor/time.

Editing a verified source invalidates its verification unless the update explicitly re-verifies it.

### 7. Run readiness verification

`GET /projects/{project_id}/verify`

The combined report includes:

- citation and quotation integrity;
- Works Cited completeness and verification;
- unresolved markers;
- import/preflight findings;
- preservation coverage;
- required metadata and front matter;
- format-profile requirements;
- active revision and profile versions.

`passed` is true only when the blocking count is zero.

### 8. Export

`POST /projects/{project_id}/exports`

Required fields:

- `formats`: `docx`, `pdf`, `md`, `txt`, or `all`;
- `acknowledge: true`;
- `expected_version`;
- `allow_review_export` only when an intentionally non-final artifact is needed.

Final export is rejected when verification fails. Review export is labelled in its manifest and filename.

The worker rechecks document version and active revision before rendering, performs post-render QA, uploads the artifact, and writes the final manifest/checksum.

## Post-render QA

DOCX validation checks:

- file reopens successfully;
- document sections exist;
- page margins match the resolved profile;
- native Word TOC field exists when required;
- unresolved markers are absent in final outputs.

PDF validation checks a valid `%PDF-` header after LibreOffice conversion.

Review outputs may retain visible unresolved markers. Structural/render corruption remains blocking in every mode.

## Revision restoration

`POST /projects/{project_id}/revisions/{revision_id}/apply`

Only `ready` revisions can be restored. Applying a revision:

- replaces canonical document JSON from the immutable snapshot;
- marks other revisions inactive;
- increments `document_version`;
- preserves every historical upload and registry record;
- changes active registry scope to the restored revision.

## Production processes

PM2 runs two processes:

- `thesis-api` — FastAPI/uvicorn.
- `thesis-worker` — one serialized ingestion/export worker.

The worker has a virtual-memory ceiling inherited by LibreOffice to protect the shared Oracle VM. Deployment creates swap when none exists.

## Readiness

`GET /readyz` returns HTTP 200 only when all required checks pass:

- PostgreSQL connection;
- database at current Alembic head;
- fresh idle/running worker heartbeat;
- no stuck jobs;
- writable storage and sufficient disk;
- LibreOffice available;
- required serif font stack available;
- production email configuration present.

`GET /healthz` proves only API liveness. Deployment must use `/readyz`.

## Deployment

From an authorized workstation:

```bash
scripts/deploy_to_oracle.sh
```

The script:

1. validates the local checkout and SSH prerequisites;
2. fetches/resets the VM checkout to the selected branch;
3. installs Python dependencies;
4. installs LibreOffice Writer and fontconfig/Liberation fonts when missing;
5. creates swap when required;
6. runs `alembic upgrade head`;
7. starts or reloads both PM2 processes;
8. requires `/healthz` and `/readyz` success;
9. saves the PM2 process list.

Do not deploy the Phase 1 branch until its PR checks pass and the PR is intentionally merged.

## Rollback

Code rollback:

```bash
cd /opt/thesis-studio-backend
git fetch origin
git reset --hard <known-good-commit>
source venv/bin/activate
alembic downgrade <compatible-revision>   # only when the code rollback requires it
pm2 startOrReload ecosystem.config.js --update-env
pm2 save
curl -fsS http://127.0.0.1:8000/readyz
```

Never delete original manuscript objects during rollback. Database downgrade from `0008` to `0006` is covered by CI migration round-trip tests.

## Known Phase 1 boundaries

- The parser is deterministic and conservative; it does not attempt AI reconstruction.
- Unsupported complex Word objects require operator review rather than automatic conversion.
- The generic Tamil Nadu profile is not a substitute for an institution-approved guide.
- A native TOC field may need Word/LibreOffice field refresh before final submission, depending on the client used to open the DOCX.
- AI writing/coaching remains a separate legacy capability; Phase 1 records no AI authorship claim for deterministic conversion.
