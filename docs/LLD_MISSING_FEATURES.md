# Acadensia — Low-Level Designs for the Missing Features

Companion to `docs/COMPETITIVE_ANALYSIS.md`. These are LLDs for the gaps that
analysis surfaced (§7) plus the items deferred while building phases 3.1–3.8.
Each is grounded in the actual v0.7.0+ codebase (head migration `0026`) and
follows the same discipline as `docs/LLD.md`. Designs, not commitments.

The six missing features, and the gap each closes:

- **MF1 Literature discovery integration** — the "no discovery corpus" gap, closed
  by *integrating* upstream search (not building a corpus).
- **MF2 Claim–citation alignment** — the deferred research half of Phase 3.
- **MF3 External deposit + ORCID** — the deferred partner integration from Phase 5.
- **MF4 Integrity Report** — the strategic "provenance instead of detection"
  alternative to Turnitin (§8), built purely on shipped phases.
- **MF5 Zotero library sync** — deeper reference-manager interop ("ingest from
  Zotero, don't fight it").
- **MF6 Public API + Word/Overleaf add-in** — the distribution gap (no external
  integration surface).

---

## Cross-cutting conventions

- **Migration numbering is build-order.** MF3, MF5 (option B), and MF6 each
  specify "migration `0027`, revises `0026`" against today's head. Only one can be
  `0027`; when they land they take consecutive ids in implementation order, each
  bumping `SCHEMA_VERSION` in lockstep across `config.py` + the three workflow
  pins + the `test_phase5_unit` assertion (the discipline that fixed the earlier
  CI break). MF1, MF2, and MF4 need **no migration**.
- **Duplicate-column trap still applies.** Any `add_column` on a table created
  model-driven must be guarded on the live column set (the 0019 pattern); new
  tables `create(..., checkfirst=True)` are safe.
- **Everything reuses shipped phases.** These features are deliberately thin: they
  compose the Phase 1 resolver, Phase 2 provenance, Phase 3 verification, Phase 5
  interop, and Phase 6 committee authz rather than adding parallel machinery. That
  is why most are low-effort and low-risk.
- **Fail-closed / never-guess is preserved.** Network features degrade to empty/
  unverifiable on error; credential-gated features do nothing without credentials;
  advisory features never gate or set human-owned flags.
- **Routers dual-mount** (`/` and `/v1`) via `API_MODULES`, and are owner-guarded
  through `fetch_owned_project`, exactly like the existing endpoints.

---

## MF1. Literature discovery integration

### Overview
A discovery layer that queries OpenAlex, Crossref, and Semantic Scholar by keyword/question, dedups the hits, and returns lightweight *candidates*. The user picks one; we then run the existing Phase 1 resolver (`service.resolve_one`) on the candidate's identifier and write a verified `Source` via `service.apply_to_source`. Acadensia stores no corpus (COMPETITIVE_ANALYSIS §3/§7: "consumes the outputs — a DOI, a source — and verifies them"); search results are ephemeral, never persisted.

### Data model & migrations
None. Candidates are transient DTOs, not rows; an added source is a normal `Source` created through the existing write-back path. Head migration stays 0026.

### Module layout
`app/references/search/` mirroring `resolvers/`:
- `base.py` — `SearchProvider` protocol, `Candidate` dataclass.
- `openalex.py`, `crossref.py`, `semantic_scholar.py` — per-authority adapters reusing `app.references.http.build_client`.
- `_registry.py` — `SEARCH_REGISTRY: tuple[SearchProvider, ...]`.
- `service.py` — `search()` orchestration + dedup; `add_candidate()`.

### Key interfaces
```python
@dataclass(frozen=True)
class Candidate:
    title: str; authors: list[str]; year: int | None
    container: str | None; doi: str | None; identifier: str  # DOI or authority URL
    authority: str; score: float

@runtime_checkable
class SearchProvider(Protocol):
    name: str
    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int) -> list[Candidate]: ...
```
`identifier` is chosen so it feeds `service.resolve_one` directly (DOI preferred; else a resolvable URL/freetext seed).

### Core flow
`search(db, query, limit)`: one shared `build_client()`, fan out to each provider concurrently (`asyncio.gather`, per-provider try/except → `[]` on error), collect candidates, dedup by normalized DOI then by a title/year key (reuse `identifiers.normalize_freetext`), sort by score. No cache write.
`add_candidate(db, project, user, identifier)`: `record = await resolve_one(db, identifier)`; create `Source(..., verified=False, parse_status="imported", identifiers={"doi": ...})`; `applied = await apply_to_source(db, source, record)`; commit. The source is resolver-verified, never guessed.

### API endpoints
New `app/api/references_search.py` (`tags=["projects"]`), registered in `API_MODULES`:
- `GET /projects/{project_id}/references/search?q=&limit=` → `{candidates: [...]}`.
- `POST /projects/{project_id}/references/search/add` — body `{identifier}` → `{source_id, applied_fields, resolution_status, retraction_status}`, mirroring `references_resolve.resolve_source`.

### Integration seams
`service.resolve_one`, `service.apply_to_source`, `models.source.Source`, `references.http.build_client`, `api.deps.fetch_owned_project`. Add-flow reuses the `references_import` source-creation shape.

### External deps & fail-closed
`httpx` only. Network gated by a new `LITERATURE_SEARCH_ENABLED` (default `True`, off in tests unless a client is injected — the `RESOLVER_ENABLED` pattern). Provider errors/timeouts → empty results, never a fabricated candidate. `SEMANTIC_SCHOLAR_API_KEY` optional.

### Test plan
`httpx.MockTransport` per provider; monkeypatch `search.service.build_client`. Assert multi-authority dedup by DOI; foreign project → 404; add-flow calls `resolve_one`/`apply_to_source` yielding a source with `resolution_status="resolved"` and populated fields (verified, not guessed); search disabled → empty, no network.

### Effort/risk
~1.5 days. Low risk: read-through + reuse of hardened write-back. Main risk is per-authority response-shape drift and dedup precision (mitigated by DOI-first keying).

---

## MF2. Claim–citation alignment

### Overview
When a manuscript sentence carries a citation, ask a sharper question than "does this quote appear in the source?": *does the cited span actually support the claim?* This scores that entailment. **Strictly advisory and probabilistic** — persisted alongside verbatim/locator checks, surfaces info-only findings, and **never gates, never sets `Quote.verified`, never emits `verified`**. **Opt-in** behind a config backend that defaults off; with no backend, every claim resolves to `unverifiable`, exactly like an unreadable source today.

### Data model & migrations
**No new table, no migration.** `QuoteVerification` (table `0024`; head `0026`) already carries `kind` with an `alignment` value plus `status`, `score`, `method`, JSONB `detail`, and `UniqueConstraint("quote_id","kind")` for one upsert-able alignment row per quote. New `detail` keys (`premise`, `hypothesis`, `rationale`) are additive JSONB — no DDL.

### Module layout
`app/verification/alignment.py`:
- `ClaimAligner` — `Protocol` (mirrors `SourceTextExtractor`).
- `NoopAligner` — default; always `unverifiable`, `method="none"`.
- `LLMClaimAligner` — adapter delegating to the JSON-only structured AI provider; an `NLIClaimAligner` may later back it with a local entailment model behind the same Protocol.

### Key interfaces
```python
AlignmentStatus = Literal["entailed", "contradicted", "unsupported", "unverifiable"]

@dataclass(frozen=True)
class AlignmentResult:
    status: AlignmentStatus
    score: float | None
    method: str            # "none" | "nli:<model>" | "llm:<model>"
    rationale: str = ""

class ClaimAligner(Protocol):
    async def align(self, premise: str, hypothesis: str) -> AlignmentResult: ...
```
`premise` = matched source span; `hypothesis` = manuscript claim sentence.

### Core flow
1. Run `verify_against_doc(quote.text, quote.page_or_loc, doc)` to get the matched span (`VerbatimResult.snippet`).
2. Pair span (premise) with the claim sentence (hypothesis) from the quote's context.
3. `await aligner.align(premise, hypothesis)`.
4. `_upsert(..., kind="alignment", status, score, method, detail={...})`; emit an **info** `QuoteFinding("claim_alignment", "info", …)`.
Default `NoopAligner` → `unverifiable`.

### Config
`CLAIM_ALIGNMENT_BACKEND: Literal["off","llm","nli"] = "off"` (the `STORAGE_BACKEND` pattern) and `CLAIM_ALIGNMENT_MODEL: str = CLAUDE_UTILITY_MODEL`. A `get_claim_aligner()` factory returns `NoopAligner` unless enabled.

### API
Extend `POST /projects/{id}/quotes/{quote_id}/verify-source` with `run_alignment: bool = False`; when true and a backend is configured, run alignment after the verbatim upsert and include the row. `/quote-verification/report` already returns all `kind`s with `advisory: True`.

### Integration seams
`verify_quote_against_source` (call the aligner after `verify_against_doc`), `_upsert` (persist `kind="alignment"`), `QuoteVerification`. No changes to `Quote`.

### Fail-closed
Missing backend, structured-output error, timeout, or provider error → `unverifiable`, `method="none"`, `detail.reason`. **Never** a silent `entailed`; absence of evidence is never evidence of support.

### Test plan
`StubAligner` deterministic → persisted `kind="alignment"` row; default `NoopAligner` → `unverifiable`; findings `info` only; workflow/gates and `Quote.verified` untouched; timeout/error → `unverifiable`, never `entailed`.

### Effort/risk
**Research-grade, high.** NLI/LLM entailment on academic prose is noisy; calibration and prompt safety are open. Advisory-only, opt-in, fail-closed containment keeps the blast radius small.

---

## MF3. External deposit and ORCID

### Overview
Deposit a finished `Export` (status `ready`) to an external repository (Zenodo or DSpace/SWORD), mint a DOI, and record the depositing author's verified ORCID. Partner/credential-gated: when tokens are unset (config defaults `""`), the feature fails closed with no network egress. Extends Phase 5 interchange, not the render pipeline.

### Data model & migrations
New `deposits` table (`app/models/deposit.py`): `id`, `export_id`→exports (RESTRICT), `project_id`, `user_id`, `target` (`zenodo|dspace`), `status` (`pending|draft_created|files_uploaded|published|failed`), `remote_id`, `doi`, `landing_url`, `orcid`, `response`(JSONB), `error_message`, `created_at`. Add to `User`: `orcid String(19)`, `orcid_verified_at DateTime(tz)`.

Migration `0027` revises `0026`: `deposits` via model-driven `create(..., checkfirst=True)`; `User` columns via the 0019 guarded pattern (inspect live columns, add only if absent). Bump `SCHEMA_VERSION` `"0026"→"0027"`.

### Module layout
`app/integrations/deposit/{base,zenodo,dspace}.py`, `app/integrations/orcid.py`, `app/services/deposit_service.py`, `app/api/deposits.py`.

### Key interfaces
```python
class DepositTarget(Protocol):
    async def create_draft(self, meta: DepositMeta) -> DepositResult: ...
    async def upload_file(self, remote_id: str, path: str, filename: str, media_type: str) -> DepositResult: ...
    async def publish(self, remote_id: str) -> DepositResult: ...
# DepositResult: remote_id, doi|None, landing_url|None, raw: dict

class OrcidClient:
    def authorize_url(self, state: str) -> str: ...
    async def exchange_code(self, code: str) -> dict: ...   # -> {orcid, name}
    async def verify(self, orcid: str, token: str) -> bool: ...
```
Each target takes an injected `httpx.AsyncClient`, enabling `MockTransport` in tests.

### Core flow
`deposit_service.create_deposit(db, export, user, target)`: require `export.status == "ready"` + `storage_key` else 409; insert `deposits` `pending`; `create_draft` from `build_thesis_document` meta → `draft_created`; `get_storage_service().download_to_temp(storage_key)` → `upload_file` with `MEDIA_TYPES[format]` → `files_uploaded` (temp cleaned in `finally`); `publish` → persist `doi`/`landing_url` → `published`. Any failure → `failed` + `error_message`. ORCID: `authorize_url` redirect, callback `exchange_code`+`verify`, persist `orcid`/`orcid_verified_at`.

### API endpoints
Owner-guarded, dual-mounted: `POST /projects/{id}/deposits` (export_id, target), `GET /projects/{id}/deposits`, `GET /deposits/{id}`; `GET /orcid/authorize`, `GET /orcid/callback`, `DELETE /orcid`.

### Integration seams
`export_service` (`build_thesis_document`, `EXPORT_FORMATS`, `MEDIA_TYPES`, `Export`), `storage_service.download_to_temp`, `Export`/`File`, `User`, `deps` guards.

### External deps & fail-closed
Zenodo REST, DSpace/SWORD, ORCID OAuth over `httpx`. New config (all default `""`): `ZENODO_TOKEN`, `ZENODO_BASE_URL` (sandbox default), `DSPACE_*`, `ORCID_CLIENT_ID/SECRET`, `ORCID_ENV` (sandbox default). Empty token → `503`, deposit row `failed`, zero network calls; sandbox default so a misconfig can't publish to production.

### Test plan
Faked `DepositTarget` asserts `pending→draft_created→files_uploaded→published` + DOI persistence; missing-token → 503 with no transport call; ORCID mocked for `exchange_code`/`verify` + unverified rejection; owner-guard 404s.

### Effort/risk
~3–4 days; partner-dependent (real Zenodo/DSpace/ORCID credentials and DSpace SWORD variance are the main risk).

---

## MF4. Integrity Report (provenance, not detection)

### Overview
A single institution-facing report that *asserts* what Acadensia already knows, rather than *detecting* plagiarism or AI text. It aggregates four shipped signals — AI-use provenance, quote-verification results, reference resolution/retraction status, and unresolved markers — into one attestable summary bound to a `document_checksum`. It runs no classifier and makes no "AI-generated"/"plagiarised" claim; absence of evidence is reported honestly as `unknown`/`unverifiable`.

### Data model & migrations
No migration. Computed on demand from existing rows (canonical document, `AIProposal`, `QuoteVerification`, `Source`) — persisting it would duplicate authoritative state and risk staleness. Optional durable binding reuses the existing `Attestation`: `create_attestation(..., attestation_type="integrity_report", statement_text=<serialised report>, context={"document_checksum": ...})`, so a sealed report is tamper-evident and joins the submission manifest — no new table earns its keep.

### Module layout
- `app/services/integrity_report.py` — pure aggregator (`build_integrity_report`).
- `app/api/integrity.py` — read endpoint; registered in `API_MODULES`.

### Key interfaces
```python
async def build_integrity_report(db: AsyncSession, project: Project) -> dict:
    # sections:
    #   ai_provenance:      (await build_rollup(db, project,
    #                         document_version=project.document_version)).to_dict()
    #   quote_verification: counts by status over verification_report(db, project.id)
    #                         -> {verified, drift, not_found, unverifiable}
    #   references:         over the project's Sources:
    #                         {resolved, unresolved, ambiguous, verified, retracted,
    #                          concern, verify_incomplete}  (missing_required per source)
    #   open_markers:       counts by MarkerBlock.kind incl. VERIFY (walk document)
    #   document_checksum:  canonical_checksum(project)
    #   ready:              per-section bool flags (see Fail-closed)
```

### Core flow
Aggregate the four existing sources; classify each `Source` via `resolution_status`, `retraction_status`, `verified`, and `missing_required(s.kind, s.fields)`. Count `MarkerBlock` kinds by walking `build_thesis_document(project)`. Compute `canonical_checksum(project)` and stamp it. No detection, no writes.

### API endpoints
`GET /projects/{project_id}/integrity-report` → serialised report. Access mirrors Phase 6: owner OR committee member holding `SupervisionPermission.VIEW_CONTENT` (`member_has_permission`; 404 on foreign project). Optional `POST .../integrity-report/attest` persists via `create_attestation`.

### Integration seams
`build_rollup` / `ProvenanceRollup.to_dict`; `verification_report`; `Source.resolution_status|retraction_status|verified|fields|kind`; `missing_required`; `MARKER_KINDS` / `MarkerBlock.kind`; `build_thesis_document`; `canonical_checksum`; `member_has_permission` + `SupervisionPermission.VIEW_CONTENT`; `Attestation` / `create_attestation`.

### Fail-closed
Never claim `verified` without a row asserting it. `QuoteVerification.unverifiable` and `resolution_status is None` surface as `unknown`, not clean. Any open `[VERIFY]`/marker or unresolved/retracted source flips that section's `ready=False`.

### Test plan
Per-section counts from fixtures (verified/drift/unverifiable quotes; retracted/ambiguous/`[VERIFY]`-incomplete sources; marker walk). Property: `unverifiable` never counted as `verified`. Checksum equals `canonical_checksum`. API: owner 200, committee-with-VIEW_CONTENT 200, foreign 404. Optional-attest round-trips into the manifest.

### Effort/risk
Low. Pure aggregation over shipped Phases 1–3/6; no migration, no model, no detection logic. Main risk is presenting `unknown` as clean — mitigated by the fail-closed flags and property tests.

---

## MF5. Zotero library sync

### Overview
Extend reference import beyond one-shot file upload to a live pull from a user's Zotero library via the Zotero Web API. Zotero speaks CSL-JSON natively, so we fetch items in `csljson` and feed them straight into the existing `from_csl_json` mapper — no new parser. Items land as unverified `Source` rows (`parse_status="imported"`), then optionally run through Phase 1 resolution to fill/verify `[VERIFY]` fields. Incremental re-sync uses Zotero's `Last-Modified-Version` cursor.

### Data model & migrations
Two options:
- **(A) Per-request key (no migration).** Client passes `api_key` + `library_id` per call; nothing stored. Zero schema change and zero secret-at-rest, but no background/incremental sync without re-supplying the key.
- **(B) `zotero_connections` table (migration `0027`, model-driven, SCHEMA_VERSION bump).** `app/models/zotero_connection.py`: `id`, `user_id`, `library_type` (`user|group`), `library_id`, `api_key_ciphertext` (encrypted, never plaintext), `last_sync_version int|null`, `created_at`.

**Recommend (A) for v1** (ship fast, no secret-at-rest), returning `last_sync_version` to the client; graduate to (B) when background sync is prioritized.

### Module layout
`app/importers/zotero.py`: thin Zotero Web API client (httpx via `build_client`) → CSL-JSON items → reuses `from_csl_json`. No mapping duplicated.

### Key interfaces
```python
async def fetch_library(
    client: httpx.AsyncClient, api_key: str, library_id: str,
    *, library_type: str = "user", since_version: int | None = None,
) -> tuple[list[dict], int]:  # (csl items, new last_modified_version)

async def import_zotero(
    db: AsyncSession, project: Project, items: list[dict],
    *, user_id: UUID, enrich: bool = False,
    client: httpx.AsyncClient | None = None,
) -> ReferenceImportResponse:
```

### Core flow
`GET https://api.zotero.org/{users|groups}/{library_id}/items?format=csljson&limit=100` with `Zotero-API-Key` header (and `If-Modified-Since-Version`). Paginate on `Link: rel=next`; read `Last-Modified-Version`. Feed the CSL array through `from_csl_json` → build `Source(..., verified=False, parse_status="imported")` as `import_references` does. If `enrich`, per source `resolve_one` then `apply_to_source` sharing one client. Commit once; return `{imported, kinds}` + cursor.

### API endpoints
`POST /projects/{project_id}/references/zotero/import` body `{api_key, library_id, library_type?, since_version?, enrich?}`. Owner-guarded; registered on the `references_import` router (dual-mounts). Reuse `_MAX_CANDIDATES=2000` + a page cap.

### Integration seams
`from_csl_json`, the `import_references` Source-creation pattern, `resolve_one`, `apply_to_source`, `Source`, `fetch_owned_project`, `build_client`.

### External deps & fail-closed
Zotero API over `httpx` (`MockTransport` offline in tests). Bad/expired key → 403 → surface as 4xx **before any DB write** (fetch fully, then insert, commit once → no partial rows). API key never logged; in option B, never stored plaintext. Enrichment respects `RESOLVER_ENABLED`.

### Test plan
`MockTransport` returns a canned `csljson` page + `Last-Modified-Version`: assert kinds created, all `verified=False`; `enrich=True` with a mocked resolver populates verified fields while placeholders stay; 403 → 4xx with zero sources committed; `since_version` sends the header and 304 yields zero imports; pagination follows `next`.

### Effort/risk
~1.5 days (option A); +0.5 day for option B. Low risk — additive, reuses the entire Phase 1 pipeline; main risks are Zotero rate limits/pagination and secret handling (mitigated by option A first).

---

## MF6. Public API and Word/Overleaf add-in

### Overview
Acadensia has no external integration surface (§7). This adds a key-authenticated public API as a *second* auth path alongside cookie/JWT — no new business endpoints. The existing owner-guarded routers (`interchange`, `references_resolve`, `references_import`) already do the work; a Word (Office.js) add-in and an Overleaf/LaTeX round-trip are *thin clients* calling them with `Authorization: Bearer <api_key>`. The only backend additions are an `api_keys` table, a CRUD router, and a key-resolving dependency yielding the same `User` as `get_current_user`.

### Data model & migrations
`api_keys` (model-driven create, migration `0027`, `down_revision="0026"`; bump `SCHEMA_VERSION`). Columns: `id`, `user_id` (FK CASCADE, indexed), `key_hash String(64)` unique+indexed, `prefix String(12)`, `scopes` (array/JSON, deny-by-default empty), `label String(120)`, `last_used_at`, `revoked_at`, `created_at`. Store only the SHA-256 hash — reuse the `sessions.py` hashing pattern. Return plaintext (`"ak_" + secrets.token_urlsafe(32)`) once at creation.

### Module layout
- `app/models/api_key.py` — `ApiKey(Base)`, mirroring `auth_token.py`.
- `app/api/api_keys.py` — CRUD router (cookie-authenticated management via `CurrentUser`).
- `app/core/api_auth.py` — the `ApiKeyAuth` dependency resolving a bearer key → `User` + scopes.
- Add-in code is a client (Office.js manifest), not backend.

### Key interfaces
```python
# app/core/api_auth.py
async def get_api_key_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User: ...
ApiKeyUser = Annotated[User, Depends(get_api_key_user)]

def require_scope(scope: str) -> Callable: ...  # 403 if scope not in key.scopes
```
`get_api_key_user` accepts only `ak_`-prefixed bearer values, hashes, looks up an unrevoked row, touches `last_used_at`, loads the `User`. Non-`ak_` values fall through so cookie/JWT still works.

### Core flow
Create → return plaintext once → client stores it → subsequent calls send `Authorization: Bearer ak_…` → hash lookup → `User` + scopes → the *existing* owner guard enforces ownership exactly as for cookies. No endpoint logic changes.

### Word add-in contract
Office.js add-in authenticates with a key, calls `GET /v1/projects/{id}/export/latex` (or `/export/jats`) and `POST /v1/projects/{id}/references/resolve[-batch]`, and inserts only *verified* citations. Zero new backend beyond `api_auth`.

### Overleaf/LaTeX round-trip
Out: `GET /v1/projects/{id}/export/latex`. In: `POST /v1/projects/{id}/import/latex/preview` (non-mutating, shipped Phase 5). Both already exist in `interchange.py`.

### API endpoints
`POST /api-keys` (create, plaintext once), `GET /api-keys` (list prefixes/labels/last_used, never the key), `DELETE /api-keys/{id}` (sets `revoked_at`). Registered in `API_MODULES`; all existing routers accept either cookie or bearer via their unchanged `CurrentUser`.

### Integration seams
To let one router accept both, generalize `get_current_user` to try `ak_` keys first (via `api_auth`) then fall back to JWT — a single branch in `deps.py`, leaving `CurrentUser` callers untouched. Reuse `sessions` hashing, the slowapi `limiter`.

### Security & fail-closed
Hash at rest (never store/log plaintext); scopes deny-by-default (empty = no access); rate-limited per key/IP; instant revocation via `revoked_at`; revoked/expired/unknown → `401`, missing scope → `403`.

### Test plan
Create key → call `/v1/projects/{id}/export/latex` with bearer → `200`. Revoke → `401`. Key lacking `export` scope → `403`. Foreign project → `404` (owner guard unchanged). Cookie path unaffected.

### Effort/risk
~2–3 days. Low risk: additive table + one dependency branch, no changes to business endpoints; main care point is the bearer-vs-key discrimination in `deps.py`.

---

## Priority — mapped to the competitive strategy

Ordered by strategic leverage per unit effort (see `COMPETITIVE_ANALYSIS.md` §8):

**Now (high leverage, low effort, pure reuse — no migration):**
1. **MF4 Integrity Report** — embodies the "provenance instead of detection"
   positioning against Turnitin, is pure aggregation of shipped phases, and is the
   single most differentiating artifact to put in front of an institutional buyer.
2. **MF1 Literature discovery** — closes the most-cited product gap ("no
   discovery") cheaply by integrating upstream and feeding the verified write-back.

**Next (distribution + interop):**
3. **MF6 Public API + add-in** — unlocks the Word/Overleaf/browser reach the
   incumbents lead with; one migration, mostly an auth path over existing endpoints.
4. **MF5 Zotero sync** — deep reference-manager interop; ship option A first (no
   migration), graduate to stored connections later.

**Later (partner-gated / research-grade):**
5. **MF3 Deposit + ORCID** — closes the write-to-published loop; gated on external
   accounts, so sequence when a partner/sandbox is available.
6. **MF2 Claim–citation alignment** — highest-ceiling, research-grade; ship the
   `NoopAligner` seam early and enable a backend once calibration is trustworthy.

Each lands in an existing seam, preserves the never-guess/fail-closed invariants,
and — for the four that need schema changes — takes the next consecutive migration
id with a `SCHEMA_VERSION` bump and a round-trip test, per the cross-cutting notes.
