# Acadensia — Low-Level Designs for the Roadmap Directions

Companion to `docs/ROADMAP.md`. Each section below is a concrete, code-grounded
low-level design for one roadmap direction: data model + migration, module
layout, real interface signatures, core algorithm, API surface, integration
seams into the existing code, external dependencies with fail-closed behavior,
a test plan, and an effort/risk/dependency read. Paths, classes, and function
names refer to the actual v0.7.0 (schema 0021) codebase.

These are designs, not commitments. Sequencing follows `ROADMAP.md` §4.

---

## Cross-cutting conventions

Concerns that recur in every design below — captured once here so each section
can stay focused.

**Migration numbering is a build-order decision, not a per-design constant.**
Every LLD below independently specifies "Alembic `0022`, revises `0021`", because
each is written against today's head. Obviously only one can be `0022`. When
these actually land, they take consecutive revision ids in implementation order
(`0022`, `0023`, …), each revising the previous head. Treat the `0022` in each
section as "the next migration after current head," not a literal id.

**Every schema-changing migration bumps `SCHEMA_VERSION`.** This is the bug we
just fixed in production: adding migrations `0019`–`0021` without bumping the
expected `SCHEMA_VERSION` made `/readyz` report `migration: false`. Each design
that adds a migration must bump `app/core/config.py::Settings.SCHEMA_VERSION`
(and the three workflow env pins + the `test_phase5_unit` assertion) to the new
head, exactly as the `0018 → 0021` fix did.

**The duplicate-column trap is mandatory reading.** Migrations `0012`, `0015`,
and `0017` create tables from live model metadata
(`Base.metadata.tables[name].create(op.get_bind(), checkfirst=True)`). On a
fresh database that path already materializes every column the model currently
declares — so a later `op.add_column` for the same column raises
`DuplicateColumnError` and aborts the chain (this is exactly what broke `0019`).
Rule for every design here: when adding a column to a model whose table is
created model-driven, guard the `add_column` on the live column set
(`sa.inspect(op.get_bind()).get_columns(table)`), and never pair a model-driven
`create_table` with an unconditional `add_column` for a field the model already
has. Brand-new tables are safe to `create_table` unconditionally.

**The test suite will not catch a broken migration.** Tests build the schema
with `create_all`, not the migration chain, so migration bugs pass CI's unit
phases and only surface in the alembic/container jobs (again, the `0019` story).
Every design that adds a migration includes a dedicated `test_migration_00xx.py`
that runs `upgrade head` → `downgrade` → `upgrade head` on a real Postgres and
asserts no duplicate-column error on the fresh path.

**Routers double-mount.** `app/main.py` includes each `API_MODULES` router once
bare (`/…`) and once under `/v1`. Every endpoint below is therefore reachable at
both prefixes automatically; new routers just get added to `API_MODULES`.

**Fail-closed / never-guess is invariant.** Every design preserves the core
discipline: a value is resolved, cited, verified, or absent — never fabricated.
Uncertain resolution, missing sources, absent credentials, and unreadable inputs
all degrade to an explicit "unknown/unverifiable/`[VERIFY]`" state, never to a
confident-but-wrong output. Advisory features (verification, alignment,
compliance warnings) surface findings; they never silently mutate the manuscript
or flip a human-owned bit.

---

## 3.1 AI provenance and authorship integrity

### Overview
Promotes `BlockIdentity.origin` (`app/canonical/model.py`) from a 3-value hint into a first-class, append-only provenance ledger keyed to block UUIDs, capturing every authorship transition at command-apply time. A new `ProvenanceService` rolls the ledger up into a policy-mapped **AI Use Statement** and a **provenance timeline**, rendered as an export section and sealed through the existing `Attestation` → `seal_submission` chain so the statement is cryptographically bound to the sealed document version and cannot be edited after the fact.

### Data model & migrations
Extend the origin vocabulary (`app/canonical/model.py`), adding two states so all four roadmap classes are representable. `manuscript_import`→imported, `human`→human-authored, `ai_proposal`→AI-suggested-accepted, plus new `ai_edited`→AI-generated-then-edited:
```python
BlockOrigin = Literal["manuscript_import", "human", "ai_proposal", "ai_edited"]
```
This is a canonical-JSON change only (blocks live in `projects.chapters` JSONB), so **no column migration** for the origin value itself; `_infer_origin` keeps back-filling legacy blocks.

**New table `provenance_events`** (append-only, model-driven via `app/models/provenance_event.py`):

| column | type | null | notes |
|---|---|---|---|
| `id` | UUID PK | no | `default=uuid4` |
| `project_id` | UUID | no | FK `projects.id` ON DELETE CASCADE |
| `block_id` | UUID | no | canonical block UUID (not an FK — blocks are JSONB) |
| `document_command_id` | UUID | yes | FK `document_commands.id` ON DELETE SET NULL |
| `ai_proposal_id` | UUID | yes | FK `ai_proposals.id` ON DELETE SET NULL |
| `origin_before` | String(40) | yes | prior `BlockOrigin` or null |
| `origin_after` | String(40) | no | resulting `BlockOrigin` |
| `action` | String(40) | no | `create`/`edit`/`accept_proposal`/`import`/`restore` |
| `actor_id` | UUID | no | FK `users.id` ON DELETE RESTRICT |
| `document_version_after` | Integer | no | matches `DocumentCommand.document_version_after` |
| `model` / `prompt_version` | String(120)/(64) | yes | copied from `AIProposal` when AI-derived |
| `detail` | JSONB | no | `default=dict` (task_mode, edited operation indexes) |
| `created_at` | DateTime(tz) | no | `server_default=func.now()` |

Indexes: `ix_provenance_project_block (project_id, block_id, created_at)`, `ix_provenance_project_version (project_id, document_version_after)`, `ix_provenance_command (document_command_id)`.

**New table `ai_use_statements`** (`app/models/ai_use_statement.py`): `id` PK, `project_id` FK CASCADE, `snapshot_id` FK `document_snapshots.id` ON DELETE RESTRICT nullable, `document_version` Integer, `document_checksum` String(64), `template_key` String(80), `granularity` String(20) (`document`/`section`/`block`), `body_text` Text, `rollup` JSONB, `content_hash` String(64), `attestation_id` FK `attestations.id` ON DELETE SET NULL nullable, `created_at`. Index `ix_ai_use_project_version (project_id, document_version)`.

**Migration** (`revises 0021`). `upgrade()`: two `op.create_table(...)` calls following the model-driven pattern of 0009 (columns + `ForeignKeyConstraint` + `create_index`). Because both tables are new, the `create_table` already declares every model column — **do not** pair it with `op.add_column` for the same fields (the 0017/0019 duplicate-column trap). No new column is added to any existing table. `downgrade()`: `op.drop_index` then `op.drop_table` for both, reverse order.

### Module layout
- `app/models/provenance_event.py` — SQLAlchemy `ProvenanceEvent` append-only ledger row.
- `app/models/ai_use_statement.py` — SQLAlchemy `AIUseStatement` generated-statement row.
- `app/provenance/__init__.py` — package.
- `app/provenance/ledger.py` — `record_transitions(...)` diffing block origins per command; called inside `editor_service._apply`.
- `app/provenance/rollup.py` — `build_rollup(...)` aggregating ledger + `AIProposal` into counts/timeline.
- `app/provenance/templates.py` — DB-free disclosure-template registry (NeurIPS, university/DPDP-aligned), mirrors `domains/profiles.py` style.
- `app/services/provenance_service.py` — orchestration: generate/read AI Use Statement, timeline, redaction granularity.
- `app/renderers/ai_use.py` — `render_ai_use_section(statement, granularity)` → canonical blocks feeding md/docx/txt/pdf.
- `app/api/provenance.py` — new router (timeline, statement generate/read).
- **Edited:** `app/canonical/model.py` (extend `BlockOrigin`), `app/services/editor_service.py` (hook `record_transitions`), `app/ai/proposal_engine.py` (tag `ai_proposal`/`ai_edited` at apply), `app/ai/disclosure.py` (delegate to `rollup.build_rollup`), `app/services/export_service.py` (inject AI Use section + statement into manifest), `app/collaboration/sealing.py` (bind statement into package manifest), `app/api/submissions.py` (`ai_use_statement` attestation type), `app/domains/profiles.py` (`disclosure_template_key` field), `app/main.py` (register router).

### Key interfaces & signatures
```python
# app/provenance/ledger.py
async def record_transitions(
    db: AsyncSession, project: Project, actor_id: UUID, *,
    document_command_id: UUID, command_type: str,
    before_doc: ThesisDocument, after_doc: ThesisDocument,
    ai_proposal: AIProposal | None = None,
) -> list[ProvenanceEvent]: ...
# Diffs block-id -> origin between before/after; emits one row per changed/new block.

# app/provenance/rollup.py
@dataclass(frozen=True)
class ProvenanceRollup:
    counts: dict[str, int]            # per BlockOrigin
    ai_block_ids: list[UUID]
    models: list[str]
    prompt_versions: list[str]
    accepted_proposals: int
    human_edited_operations: int
    timeline: list[dict]              # ordered transition records

async def build_rollup(db: AsyncSession, project: Project, *, document_version: int) -> ProvenanceRollup: ...

# app/provenance/templates.py
@dataclass(frozen=True)
class DisclosureTemplate:
    key: str
    label: str
    policy_ref: str
    render: Callable[[ProvenanceRollup, ThesisMeta], str]
def get_disclosure_template(key: str) -> DisclosureTemplate: ...   # raises UnknownDisclosureTemplate (fail-closed)

# app/services/provenance_service.py
async def generate_ai_use_statement(
    db: AsyncSession, project: Project, *,
    template_key: str, granularity: Literal["document","section","block"],
) -> AIUseStatement: ...
async def get_provenance_timeline(db: AsyncSession, project: Project, *, block_id: UUID | None = None) -> list[dict]: ...
```

### Core algorithm / flow
1. **Capture at edit time.** `editor_service._apply` already computes `document` (before) and `result.document` (after) and records the `DocumentCommand`. Immediately after `_record_command`, call `record_transitions(before_doc, after_doc, document_command_id=command.id, ...)`. It builds `{block_id: origin}` maps for both docs (reusing `compare_documents`' block-walk logic), and for every new or origin-changed block writes a `ProvenanceEvent` — inside the same transaction, so provenance commits atomically with the command (never a silent mutation).
2. **Origin assignment.** Human editor commands set `origin="human"`. In `proposal_engine`, an accepted proposal applied unchanged tags target blocks `ai_proposal`; if the proposal's `human_edited_operations` touched a block, or a later human command edits an `ai_proposal` block, `record_transitions` promotes it to `ai_edited`. `manuscript_import` stays from `_infer_origin`.
3. **Rollup.** `build_rollup` scans `provenance_events` up to `document_version`, joins `AIProposal` (models, prompt_versions, `selected_operation_indexes`, `human_edited_operations`) — replacing the ad-hoc query in `ai/disclosure.py` — and produces per-origin counts plus an ordered timeline.
4. **Statement generation.** `generate_ai_use_statement` resolves the template from `project.domain_profile`'s `disclosure_template_key` (or explicit override), renders `body_text`, applies redaction `granularity`, computes `content_hash = sha256(body_text + document_checksum)`, persists an `AIUseStatement` bound to `document_version` + `canonical_checksum(project)`.
5. **Export.** `export_service.run_export` calls `render_ai_use_section` and inserts the block into the document (or as an `ai_disclosure` `FrontMatterEntry`), and stores `rollup`+`content_hash` in `manifest["ai_provenance"]`, superseding today's `ai_involvement`.
6. **Seal.** Author records an `ai_use_statement` attestation via `create_attestation`; `seal_submission` embeds `{statement_id, content_hash, template_key}` into the package `manifest`, and `_package_checksum` covers it — so the disclosure is tamper-evident against the sealed version.

### API endpoints
New `app/api/provenance.py`, `tags=["provenance"]`, guarded by `require_project_capability(..., "project.read_metadata")` / `"submission.attest"`:

- `GET /projects/{project_id}/provenance/timeline?block_id=` → `{"document_version": int, "events": [{"block_id","origin_before","origin_after","action","actor_id","model","prompt_version","document_version_after","created_at"}]}`
- `GET /projects/{project_id}/provenance/summary` → `ProvenanceRollup` as JSON (`counts`, `ai_block_ids`, `models`, `prompt_versions`, `accepted_proposals`, `human_edited_operations`).
- `POST /projects/{project_id}/ai-use-statement` — body `{"template_key": str, "granularity": "document|section|block"}` → `{"id","template_key","granularity","body_text","content_hash","document_version","document_checksum","created_at"}`.
- `GET /projects/{project_id}/ai-use-statement?version=` → latest statement for that version (404 if none).

The signing step reuses the existing `POST /projects/{project_id}/attestations` (`app/api/submissions.py`) with new `attestation_type` literal `"ai_use_statement"` added to `AttestationCreate`; `context` carries `{statement_id, content_hash}`.

### Integration seams
- `app/canonical/model.py`: `BlockOrigin`, `BlockIdentity.origin`, `_infer_origin` (extend vocabulary; leave inference intact).
- `app/services/editor_service.py`: `_apply` / `_record_command` (before/after docs, `command.id`) — insertion point for `record_transitions`.
- `app/ai/proposal_engine.py`: proposal-apply path setting `AIProposal.applied_command_id`, `selected_operation_indexes`, `human_edited_operations` — source of AI tagging; `app/api/ai_partner.py::decide_ai_proposal`.
- `app/ai/disclosure.py::ai_disclosure_summary`: refactored to call `rollup.build_rollup`, preserving its dict shape and `truth_notice`.
- `app/services/export_service.py::run_export`: `manifest["ai_involvement"]` / `report["ai_disclosure"]` → extended to embed statement + `content_hash`.
- `app/collaboration/sealing.py::seal_submission` (manifest builder + `_package_checksum`) and `create_attestation`; `app/models/review_collaboration.py::Attestation`.
- `app/domains/profiles.py::DomainProfile`: add `disclosure_template_key: str = ""`.
- `app/models/event.py::Event`: emit `kind="provenance_transition_recorded"` alongside ledger rows for the existing audit stream.

### External dependencies & fail-closed behavior
No new runtime libraries — reuses `hashlib` (checksums, as in `sealing._package_checksum`), stdlib only. **Fail-closed:** `get_disclosure_template` raises `UnknownDisclosureTemplate` rather than emitting a generic statement; a project whose `domain_profile`/`disclosure_template_key` doesn't resolve cannot generate a statement (the endpoint returns 409). A block with `origin=None` is reported literally as "unknown/legacy" and never guessed as human. Statement generation refuses if `document_checksum` no longer matches `canonical_checksum(project)` (stale). The AI Use section is never silently auto-inserted at final export without a persisted, version-matched `AIUseStatement`; absent one, export records "no AI-use statement generated" — never a fabricated disclosure. Origins are author-declared/derived from real command history, never inferred by a detector (roadmap §6 non-goal).

### Test plan
- `tests/test_provenance_ledger.py`: human edit → `ai_proposal` accept → subsequent human edit produces `human`→`ai_proposal`→`ai_edited` transitions; ledger commits atomically with `DocumentCommand` (rollback on command failure leaves no orphan rows); `manuscript_import` blocks emit no spurious `human` events.
- `tests/test_provenance_rollup.py`: `build_rollup` counts per origin, dedups models/prompt_versions, matches `human_edited_operations` from `AIProposal`; version filter excludes commands past `document_version`.
- `tests/test_ai_use_statement.py`: `document`/`section`/`block` granularity redaction; `content_hash` stability; stale-checksum refusal; unknown template → 409.
- `tests/test_provenance_api.py`: timeline/summary/generate endpoints on both `/` and `/v1`; capability enforcement (non-member 403); `ai_use_statement` attestation accepted only from author.
- `tests/test_export_ai_use.py`: AI Use section present in md/docx/txt; `manifest["ai_provenance"].content_hash` populated; no statement → labelled absence, not fabrication.
- `tests/test_seal_provenance_binding.py`: sealed package manifest embeds statement hash; tampering the statement body invalidates `_package_checksum` comparison.
- `tests/test_migration_provenance.py`: upgrade/downgrade round-trip; both tables created with no duplicate-column error.

### Effort, risk, dependencies
**Effort: M** — ~2 new tables, one thin migration, one aggregation service, one export section, and edit-time hooks; the model groundwork (`BlockOrigin`, attestation chain, `ai_disclosure_summary`) already exists. **Risks:** (1) policy accuracy — the disclosure templates must mirror real NeurIPS/institutional wording, so `templates.py` is a research-the-policy-first task, not a formatting guess (highest risk); (2) correctly promoting `ai_proposal`→`ai_edited` across multi-block/partial-accept commands; (3) keeping `ai_disclosure_summary`'s public dict shape stable so `export_service`/manifest consumers don't break. **Dependencies:** builds only on shipped Phase 2/4; independent of 3.2. **Unblocks:** 3.8 (research corpus) is explicitly gated behind this; strengthens 3.6 supervisor verification.

---

## 3.2 Reference enrichment and reconciliation

### Overview
Resolve `[VERIFY]` placeholders on registry `Source` rows automatically: given a DOI / arXiv id / ISBN / messy free-text citation, query an ordered authority chain (Crossref → OpenAlex → Semantic Scholar → arXiv → Unpaywall → ISBN), merge into a normalized record with per-field confidence + source authority, retraction-check it, and write back only fields that clear a confidence threshold — anything unresolved stays `[VERIFY]` (`field_schema._is_missing`). Results are cached by identifier so re-runs and rate limits don't re-hit the network. This feeds the existing source model and `field_schema.missing_required` rather than replacing them.

### Data model & migrations
Two new tables plus additive columns on `sources`. Follow the model-driven create pattern of `0017`, and the `0019` guard trap: on a fresh DB the model metadata already materializes every column the model declares, so any column also touched by a later migration must be guarded on the live column set (`sa.inspect(bind).get_columns(table)`). Add columns via explicit `op.add_column` (like `0021`) since `sources` already exists.

New table `resolution_records` (resolver cache, one row per resolved identifier/query):
- `id` PG UUID PK
- `identifier_kind` `String(20)` NOT NULL (`doi|arxiv|isbn|openalex|freetext_hash`)
- `identifier_value` `String(300)` NOT NULL — for free-text this is a normalized sha256 hash
- `status` `String(20)` NOT NULL (`resolved|unresolved|ambiguous`)
- `canonical` `JSONB` NOT NULL default `{}` — merged normalized record (title/author/container/year/...)
- `provenance` `JSONB` NOT NULL default `{}` — per-field `{field: {authority, confidence, fetched_at, raw}}`
- `candidates` `JSONB` NOT NULL default `[]` — variant records seen (dedup audit)
- `retraction` `JSONB` NULL — `{retracted: bool, kind, notice_doi, source, checked_at}`
- `authorities_tried` `JSONB` NOT NULL default `[]`
- `fetched_at` / `expires_at` `DateTime(tz=True)` NOT NULL / NULL (TTL for cache invalidation)
- `created_at` `DateTime(tz=True)` server_default now()
- UniqueConstraint `(identifier_kind, identifier_value)` name `uq_resolution_identifier`; index on `expires_at`.

New table `source_field_provenance` (per-field, per-source, for the merge-back audit surfaced in readiness):
- `id` PK, `source_id` FK `sources.id` ondelete CASCADE, index
- `field_name` `String(60)` NOT NULL, `value` `Text` NULL
- `authority` `String(30)` NOT NULL, `confidence` `Float` NOT NULL
- `resolution_record_id` FK `resolution_records.id` ondelete SET NULL, NULL
- `applied` `Boolean` NOT NULL default False, `created_at`
- UniqueConstraint `(source_id, field_name)` name `uq_source_field_provenance`.

Additive columns on `sources`: `resolution_status` `String(20)` NULL, `retraction_status` `String(20)` NULL (`none|retracted|concern`), `canonical_key` `String(120)` NULL index (dedup collapse key), `alternate_keys` `JSONB` NOT NULL default `[]`. `verification_method` gains a new value `"resolver"`.

Migration `reference_enrichment` (`down_revision="0021"`), `import app.models  # noqa: F401` to register metadata. `upgrade()` creates the two tables via `Base.metadata.tables[...].create(bind, checkfirst=True)` and guards each `op.add_column` on `_columns("sources")`. `downgrade()` drops the added `sources` columns (guarded) then `.drop(bind, checkfirst=True)` the two tables. Bump `Settings.SCHEMA_VERSION` in `app/core/config.py`.

### Module layout
```
app/references/
  __init__.py
  identifiers.py          # detect/normalize DOI, arXiv, ISBN, free-text
  resolvers/
    __init__.py           # REGISTRY: ordered tuple of Resolver instances
    base.py               # Resolver Protocol, ResolvedRecord, FieldValue
    crossref.py           # CrossrefResolver
    openalex.py           # OpenAlexResolver
    semantic_scholar.py   # SemanticScholarResolver
    arxiv.py              # ArxivResolver
    unpaywall.py          # UnpaywallResolver
    isbn.py               # IsbnResolver (Google Books / OpenLibrary)
  reconcile.py            # merge + confidence + dedup
  retraction.py           # Crossref update-to + Retraction Watch check
  cache.py                # get/put ResolutionRecord (async, DB-backed)
  service.py              # resolve_one / resolve_batch / apply_to_source
  mapping.py              # ResolvedRecord.field -> registry kind/fields
```
The registry mirrors the citation-style registry pattern (an ordered collection behind one interface).

### Key interfaces & signatures
```python
# app/references/resolvers/base.py
@dataclass(frozen=True)
class FieldValue:
    value: str
    authority: str          # "crossref" | "openalex" | ...
    confidence: float       # 0.0–1.0
    raw: str | None = None

@dataclass
class ResolvedRecord:
    identifier_kind: str
    identifier_value: str
    fields: dict[str, FieldValue] = field(default_factory=dict)  # registry field -> value
    source_type: str | None = None      # article/book/... (source_types vocab)
    retraction: dict | None = None
    authority: str = ""
    fetched_at: datetime | None = None
    matched: bool = False

class Resolver(Protocol):
    name: str
    def handles(self, id_kind: str) -> bool: ...
    async def resolve(self, client: "httpx.AsyncClient",
                      id_kind: str, id_value: str,
                      hint: dict | None = None) -> ResolvedRecord | None: ...

# app/references/identifiers.py
def detect_identifier(text: str) -> tuple[str, str]: ...   # ("doi","10.x/..") | ("freetext", sha)

# app/references/reconcile.py
def merge(records: list[ResolvedRecord]) -> ResolvedRecord: ...        # field-wise, authority-weighted
def canonical_key(rec: ResolvedRecord) -> str: ...                     # dedup collapse key
def dedup(candidates: list["Source"]) -> dict[str, list[UUID]]: ...    # key -> source ids

# app/references/service.py
async def resolve_one(db, query: str, kind_hint: str | None = None) -> ResolutionRecord: ...
async def resolve_batch(db, queries: list[str]) -> list[ResolutionRecord]: ...
async def apply_to_source(db, source: "Source", rec: ResolutionRecord,
                          min_confidence: float = 0.75) -> list[str]: ...  # returns applied field names
```

### Core algorithm / flow
1. **Detect** — `detect_identifier(query)` classifies to `doi|arxiv|isbn|freetext`. Free-text is normalized (lowercase, collapse whitespace, strip punctuation) and hashed for the cache key.
2. **Cache lookup** — `cache.get(db, id_kind, id_value)`; if a non-expired `resolution_records` row exists, return it (no network).
3. **Chain** — iterate `resolvers.REGISTRY` in order; call `resolve()` only on resolvers whose `handles(id_kind)` is true. Crossref is authoritative for DOIs/journal metadata; OpenAlex is the broad fallback; Semantic Scholar adds CS/AI depth; arXiv handles preprints; Unpaywall only enriches OA links onto an already-matched DOI; ISBN services handle books. Collect every non-None `ResolvedRecord`. One shared `httpx.AsyncClient` (polite User-Agent, per-host semaphore).
4. **Reconcile / merge** — `merge(candidates)` picks each field's value by highest `FieldValue.confidence`, tie-broken by a static authority-rank (crossref > openalex > s2 > arxiv). Field confidence = authority weight × agreement bonus. Records are grouped by `canonical_key` (normalized title + first-author surname + year, or shared DOI) so the same work cited three ways collapses to one canonical record with the others' identifiers preserved in `alternate_keys`.
5. **Retraction** — `retraction.check(client, doi)` queries Crossref `relation.is-retracted` / update-to notices and Retraction Watch; sets `retraction` and maps to `sources.retraction_status`. Surfaced in readiness so a thesis never unknowingly cites a retracted work.
6. **Persist** — write/update the `resolution_records` row.
7. **Apply-back** — `apply_to_source` maps via `mapping.to_registry_fields(rec, source.kind)` (field names from `field_schema`; `source_type` from `source_types.source_type_for_kind`). Only fields currently missing per `field_schema._is_missing` **and** whose merged confidence ≥ `min_confidence` are written; each writes a `source_field_provenance` row. Fields below threshold or absent stay `[VERIFY]`. Retracted works never auto-verify.

### API endpoints
Owner-guarded via `fetch_owned_project` (foreign project → 404).
- `POST /projects/{project_id}/references/resolve` — resolve one. Request `{"query": "10.1038/nphys1170", "kind_hint": "journal"?}` → `{"status":"resolved","identifier":{...},"fields":{"title":{"value":"...","authority":"crossref","confidence":0.98}, ...},"source_type":"article","retraction":{"retracted":false},"authorities_tried":["crossref","unpaywall"]}`
- `POST /projects/{project_id}/references/resolve-batch` — `{"queries":[...]}` → `{"results":[...],"resolved":N,"unresolved":M}`.
- `POST /projects/{project_id}/sources/{source_id}/resolve` — resolve + apply. Request `{"expected_version": <int>, "min_confidence": 0.75?}` → `{"source_id":"...","applied_fields":["container","doi_or_url"],"still_missing":["pages"],"retraction_status":"none","document_version":<int+1>}`; emits `Event(kind="source_resolved")`.

### Integration seams
- `app/api/references_import.py::import_references` — after inserting imported `Source` rows, optionally inline `resolve_one` per candidate carrying a DOI/ISBN/arXiv id; response gains an optional `resolved` count.
- `app/renderers/bibtex_import.py::from_bibtex` — candidates already surface `doi_or_url`/`url`; `identifiers.detect_identifier` reads those as the resolution seed.
- `app/renderers/field_schema.py::missing_required` / `_is_missing` — authority on what still needs resolving and what stays `[VERIFY]`; `field_schema_for_kind` supplies target field names.
- `app/models/source.py::Source` — write target; new columns + `verification_method="resolver"`.
- `app/renderers/source_types.py::source_type_for_kind` — reused to stamp `source_type`.
- Readiness/verifier (`app/ingest/verifier.py`) — consumes `retraction_status` to raise a blocking issue for retracted works.

### External dependencies & fail-closed behavior
`httpx==0.28.1` already a dependency. No new runtime packages. New optional settings (`CROSSREF_MAILTO`, `UNPAYWALL_EMAIL`, `SEMANTIC_SCHOLAR_API_KEY`, `RESOLVER_ENABLED`, `RESOLUTION_TTL_DAYS`). Rate-limit handling: per-host `asyncio.Semaphore`, exponential backoff on 429/503, hard per-query timeout; on exhaustion the resolver returns `None`. **Fail-closed:** any transport error, timeout, ambiguous match, or below-threshold confidence yields no field write — `[VERIFY]` preserved by `_is_missing`, `resolution_status="unresolved"`, `verified` stays False. Cache (`resolution_records` with `expires_at` TTL) absorbs re-runs; source authority always stored/returned so a human can override.

### Test plan
Offline & deterministic — inject `httpx.MockTransport`/`respx`; fixtures under `tests/fixtures/resolvers/`.
- `tests/test_reference_identifiers.py` — DOI/arXiv/ISBN/free-text detection & hashing.
- `tests/test_reference_resolvers.py` — each adapter parses captured payload; 404/429/timeout → `None`.
- `tests/test_reference_reconcile.py` — `merge` highest-confidence + agreement boost + tie-break; `canonical_key`/`dedup` collapse; conflicting fields lower confidence.
- `tests/test_reference_retraction.py` — retracted vs clean DOI mapping.
- `tests/test_reference_apply.py` — writes only missing + high-confidence, leaves `[VERIFY]`, records provenance, never auto-verifies a retracted work.
- `tests/test_references_resolve_api.py` — owner guard (404), `expected_version` conflict (409), resolve→apply flips `missing_required` to empty, cache hit avoids second call.
- `tests/test_migration_reference.py` — fresh-DB create + guarded add_column idempotency + downgrade round-trip.

### Effort, risk, dependencies
**Effort: M.** No new heavy deps; leans on `httpx`, `Source`, `field_schema`, router + alembic patterns. **Risks:** rate limits (→ cache/TTL/backoff), metadata quality (→ per-field confidence + fail-closed writes), free-text ambiguity (→ `ambiguous`, no write), migration duplicate-column trap (→ guarded add_column). **Unblocks:** trustworthy verified input, retraction surfacing in readiness (3.3), multilingual metadata via OpenAlex (3.7).

---

## 3.3 Quotation and claim verification

### Overview
Given a source artifact (PDF/EPUB/HTML) attached to a registry `Source`, this feature confirms that a `Quote.text` appears verbatim in that source at the cited `Quote.page_or_loc`, flags transcription/paraphrase drift, and — as a research-grade opt-in half — scores whether the cited span *entails* the manuscript sentence (claim–citation alignment). Every output is **advisory**: it produces `warn`/`info` findings surfaced through the existing verification/readiness services and sets an evidence status of `verified | drift | not_found | unverifiable`, never flipping the human `Quote.verified` bit and never adding a `block`-severity finding. It extends the never-guess core: a missing or unreadable source fails closed to `unverifiable`, never to `verified`.

### Data model & migrations
Two additions. First, source-artifact storage — `Source` today has **no** storage key (unlike `ManuscriptRevision.storage_key/mime_type/size_bytes/checksum`), so the source document to quote-check against cannot be located. Add nullable columns to `sources` mirroring the revision pattern:
```
sources.artifact_storage_key   String(700)  NULL
sources.artifact_mime_type     String(150)  NULL   # application/pdf | application/epub+zip | text/html
sources.artifact_size_bytes    BigInteger   NULL
sources.artifact_checksum      String(64)   NULL   # sha256, dedup + cache key for extracted text
```
Second, a new result table `quote_verifications` (one row per (quote, revision) check; claims stored in the same table discriminated by `kind`):
```
quote_verifications
  id                 PG_UUID   PK  default uuid4
  quote_id           PG_UUID   FK quotes.id           ondelete=CASCADE  NOT NULL index
  source_id          PG_UUID   FK sources.id          ondelete=CASCADE  NOT NULL index
  project_id         PG_UUID   FK projects.id         ondelete=CASCADE  NOT NULL index
  user_id            PG_UUID   FK users.id            ondelete=CASCADE  NOT NULL index
  import_revision_id PG_UUID   FK manuscript_revisions.id ondelete=SET NULL NULL index
  kind               String(20)  NOT NULL  default 'verbatim'   # verbatim|locator|paraphrase|alignment
  status             String(20)  NOT NULL                       # verified|drift|not_found|unverifiable|misplaced|entailed|contradicted|unsupported
  score              Float       NULL                           # 0..1 similarity / entailment prob
  method             String(40)  NOT NULL                       # 'rapidfuzz.partial_ratio' | 'nli:<backend>@<ver>' | 'none'
  matched_locator    String(100) NULL
  matched_span       JSONB       NOT NULL default dict          # {char_start,char_end,page,snippet,normalized}
  detail             JSONB       NOT NULL default dict          # thresholds, diff, extractor_version, source_checksum
  checked_at         DateTime(tz) NOT NULL server_default now()
  UniqueConstraint(quote_id, import_revision_id, kind)  name=uq_quote_verification_scope
  Index ix_qv_project_kind (project_id, kind)
```
**Migration** (`revises 0021`). `quote_verifications` is a brand-new table → safe to `op.create_table(...)` unconditionally. The `sources.artifact_*` columns are model-driven — guard each `add_column` exactly like 0019's `last_event_at` fix (`if name not in _cols("sources")`) to avoid `DuplicateColumnError` on fresh installs. This is precisely the 0017/0019 trap: never blind-`add_column` a column the model also declares.

### Module layout
```
app/verification/
  __init__.py
  quotes.py            # QuoteVerifier orchestration, normalization, fuzzy match, locator check
  alignment.py         # ClaimAligner protocol + NoopAligner + backend adapters (research half)
  extractors/
    base.py            # SourceTextExtractor Protocol, ExtractedDoc, ExtractorError
    pdf.py             # PdfExtractor  (pypdf/pdfminer.six)
    epub.py            # EpubExtractor (ebooklib + html)
    html.py            # HtmlExtractor (defusedxml)
    registry.py        # get_extractor(mime_type) -> SourceTextExtractor
  normalize.py         # unicode NFKC, quote/dash/ellipsis folding, whitespace collapse, ligatures
app/services/quote_verification_service.py   # DB-facing: load source artifact, persist rows, revision scoping
app/models/quote_verification.py             # the ORM model above
app/api/quote_verification.py                # endpoints
```

### Key interfaces & signatures
```python
# app/verification/extractors/base.py
@dataclass(frozen=True)
class PageText:
    locator: str          # "12", "iv", "loc:1840", "#section-3"
    text: str
@dataclass(frozen=True)
class ExtractedDoc:
    pages: list[PageText]
    full_text: str
    extractor: str        # "pypdf@3.x"
    source_checksum: str
class ExtractorError(RuntimeError): ...   # -> status "unverifiable", never raised past service
@runtime_checkable
class SourceTextExtractor(Protocol):
    mime_types: tuple[str, ...]
    def extract(self, local_path: str) -> ExtractedDoc: ...

# app/verification/quotes.py
@dataclass(frozen=True)
class VerbatimResult:
    status: Literal["verified","drift","not_found"]
    score: float
    matched_locator: str | None
    matched_span: dict
    method: str
def find_best_span(needle: str, haystack: str, *, min_score: float) -> VerbatimResult: ...
def verify_locator(result: VerbatimResult, cited_locator: str, doc: ExtractedDoc) -> Literal["match","misplaced","unknown"]: ...
class QuoteVerifier:
    def __init__(self, extractor, verbatim_threshold=0.97, drift_threshold=0.85): ...
    def verify(self, quote_text: str, cited_locator: str, local_path: str) -> list["QuoteFinding"]: ...

# app/verification/alignment.py  (research half — advisory, opt-in)
@dataclass(frozen=True)
class AlignmentResult:
    status: Literal["entailed","contradicted","unsupported","unverifiable"]
    score: float
    method: str            # "nli:noop" | "nli:anthropic@<model>" | "nli:local-mnli@<ver>"
class ClaimAligner(Protocol):
    def align(self, premise: str, hypothesis: str) -> AlignmentResult: ...
class NoopAligner:         # default when no backend configured -> always "unverifiable"
    def align(self, premise, hypothesis) -> AlignmentResult: ...
```

### Core algorithm / flow
All steps are **advisory** (`severity in {"warn","info"}`, write a `QuoteVerification` status, never set `Quote.verified`, never `block`).
1. **Locate artifact.** Load `Source.artifact_storage_key` via `get_storage_service().download_to_temp(key)`. Missing key / `ExtractorError` / empty text → persist `status="unverifiable"`, `method="none"`; stop (fail closed).
2. **Extract.** `get_extractor(mime_type).extract(temp_path)` → `ExtractedDoc` with per-page locators. Cache by `artifact_checksum`.
3. **Normalize.** NFKC, fold curly→straight quotes, en/em dash→hyphen, `…`→`...`, ligatures, collapse whitespace, strip elision ellipses; keep a normalized→raw offset map for snippet recovery.
4. **Fuzzy verbatim match.** `rapidfuzz.fuzz.partial_ratio_alignment(needle, haystack, score_cutoff=drift*100)`. `score ≥ 0.97` → `verified`; `0.85 ≤ score < 0.97` → `drift` (`warn` `quote_verbatim_drift` with token diff); `< 0.85` → `not_found` (`warn`).
5. **Locator/page verification.** Best span's page vs `Quote.page_or_loc` (strip "p."/"pp.", roman numerals, ranges). Mismatch → `info` `quote_locator_mismatch`.
6. **Paraphrase attribution** (project sweep): uncited manuscript sentence with high match (≥0.9) against a cited-elsewhere source → `info` `possible_uncited_paraphrase`. Advisory nudge.
7. **Claim–citation alignment (research half, opt-in).** Only when `settings.CLAIM_ALIGNMENT_BACKEND` set. Premise = matched span expanded to sentence; hypothesis = the manuscript sentence carrying the citation. `ClaimAligner.align(...)` → `entailed|contradicted|unsupported`, `info`-only finding. Default `NoopAligner` → `unverifiable`, no finding. Explicitly probabilistic; surfaced with backend name.

### API endpoints
- `POST /projects/{project_id}/quotes/{quote_id}/verify-source` — `{"run_alignment": false}` → `{"quote_id":"...","kind":"verbatim","status":"drift","score":0.91,"method":"rapidfuzz.partial_ratio_alignment","matched_locator":"42","cited_locator":"41","matched_span":{...},"findings":[{"rule":"quote_verbatim_drift","severity":"warn","diff":[...]},{"rule":"quote_locator_mismatch","severity":"info"}],"checked_at":"..."}`
- `POST /projects/{project_id}/quote-verification/run` (background job; scoped to `project.active_revision_id`) → `{"job_id":"...","queued":37,"skipped_no_artifact":4}`
- `GET /projects/{project_id}/quote-verification/report` → `{"revision_id":"...","counts":{"verified":30,"drift":3,"not_found":1,"unverifiable":4,"misplaced":2},"alignment":{"entailed":10,"unsupported":2,"unverifiable":25},"advisory":true,"results":[...]}`. `advisory:true` always present so clients never render these as gates.

### Integration seams
- `app/services/verification_service.py::verify_project` — after `_format_violations`, append `warn`/`info` quote findings; never increments `counts["block"]`; `pass` stays block-driven (advisory preserved). Scope via existing `active_revision_rows`.
- `app/api/domain_profiles.py::project_domain_readiness` — add a `quote_verification` summary block (advisory).
- `app/services/readiness_service.py::readiness_report` — add a `checks["quote_extractors"]` probe; extractor absence must not flip overall readiness for the verbatim path.
- Canonical quote blocks — `BlockQuoteBlock.quote_id` / `VerseQuoteBlock.quote_id` link canonical blocks to `Quote` rows; paraphrase sweep walks `ParagraphBlock.runs`. Alignment reuses the `CitationResolution` `(block_id, raw_citation)->source_id` map in `verify_project`.
- Storage — `app/services/storage_service.py::get_storage_service()` + `download_to_temp`; artifacts uploaded through the `references_import` upload path.
- Human verify bit untouched — `manuscripts.py::verify_quote` keeps sole authority over `Quote.verified`.

### External dependencies & fail-closed behavior
Repo has no PDF *text extraction* dep today (PDF is only written/header-checked via LibreOffice). Add `pypdf` (pure-Python, deterministic) primary, optional `pdfminer.six` fallback; `ebooklib` + `defusedxml` (already a dep) for EPUB/HTML; `rapidfuzz` (C-backed, deterministic) for matching. Alignment backend pluggable behind `ClaimAligner`; default `NoopAligner` (no dep); optional `anthropic` (already a dep) or local MNLI — **opt-in via `settings.CLAIM_ALIGNMENT_BACKEND`**, never required to boot. **Fail-closed:** any of {no artifact key, download failure, unknown MIME, `ExtractorError`, empty text, aligner unset/timeout} → `status="unverifiable"`, `score=None`, `method="none"`, no `warn`/`block`. Only a real ≥0.97 match reaches `verified`. Unverifiable is never conflated with verified.

### Test plan
Deterministic, offline; fixture artifacts under `tests/fixtures/sources/`.
- `tests/test_verification_normalize.py` — folding + offset-map round-trips.
- `tests/test_verification_extractors.py` — sample.pdf/epub/html per-page extraction; corrupt file → `ExtractorError`; MIME dispatch.
- `tests/test_quote_verbatim.py` — exact → `verified` 1.0; single-typo → `drift` with diff; unrelated → `not_found`; right words wrong page → `verified` + locator mismatch; locator normalization.
- `tests/test_quote_verification_service.py` — one row per (quote, revision, kind); upsert on re-run; missing artifact → `unverifiable` (never `verified`); active-revision scoping; storage mocked.
- `tests/test_alignment.py` — `NoopAligner` → `unverifiable`; stub aligner fixed labels; findings capped at `info`.
- `tests/test_quote_verification_api.py` — three endpoints on `/` and `/v1`; `verify_project` adds only `warn`/`info` and leaves `pass`/`block` unchanged; 404 on foreign quote.
- `tests/test_migration_quote_verification.py` — upgrade where `sources.artifact_*` already exist (fresh path) does not raise `DuplicateColumnError`; downgrade clean.

### Effort, risk, dependencies
**S** schema/storage seam (low risk, mirrors `manuscript_revision`); **M** verbatim + locator + extractors (deterministic, fully testable offline); **L** claim–citation alignment (research-grade — entailment accuracy, non-determinism, latency/cost; mitigated by `NoopAligner` default, `info`-only, `advisory:true`, surfaced backend). New deps `pypdf`, `rapidfuzz`, `ebooklib` (+ optional `pdfminer.six`); reuse `defusedxml`, `anthropic`, storage, `Job` queue. No dependency on 3.2; benefits from 3.1 if artifacts arrive via importers.

---

## 3.4 Venue and submission compliance

### Overview
Turn `DomainProfile` from a passive template into an enforcing gate by attaching an ordered tuple of pure, config-driven `ProfileValidator`s (page budget, double-blind anonymization lint, reproducibility checklist) that run against the compiled artifact plus the canonical `ThesisDocument`. Findings surface through a new compliance endpoint beside the advisory `GET /projects/{id}/domain-readiness`, reusing the same `project.meta["domain_profile"]` selector and the profile's `submission_checklist`. A fourth capability — deterministic camera-ready formatting — is a thin config layer over the existing `render_docx` path.

### Data model & migrations
**No migration.** Validators are pure functions of `(ThesisDocument, CompiledArtifact, DomainProfile)`; the profile registry in `app/domains/profiles.py` is already "DB-free: pure data plus lookup helpers." Compliance is computed on demand (like `project_domain_readiness`) and needs no persistence to be correct. Venue budgets (page limits, anonymized-link allowlists) live as literal fields on frozen dataclasses in code, versioned with the code. The only case for a migration is *caching* the last compliance run at seal time — fold it into the existing `submission_packages.manifest` JSON with zero DDL. **Recommendation: ship stateless first; add a migration only when sealing needs an immutable compliance record.**

### Module layout
New package `app/domains/validators/`, parallel to the citation-style registry:
```
app/domains/validators/
    __init__.py          # registry: get_validator(key), run_profile(profile, ctx)
    base.py              # ProfileValidator Protocol, ValidationFinding, ComplianceContext, Severity
    page_budget.py       # PageBudgetValidator
    anonymization.py     # DoubleBlindValidator
    reproducibility.py   # ReproducibilityChecklistValidator
    camera_ready.py      # CameraReadySpec + deterministic-format resolver (config, not a validator)
```
`DomainProfile` gains `validators: tuple[str, ...]` (keys resolved through the registry, exactly as `default_citation_style` resolves through `get_citation_style`) and `page_limit: int | None`. `_NEURIPS_PAPER` → `("page_budget","double_blind","reproducibility")`, `_CVPR_PAPER` → `("page_budget","double_blind")`, non-venue profiles keep `validators=()` and behave exactly as today.

### Key interfaces & signatures
```python
# app/domains/validators/base.py
Severity = Literal["block", "warn", "info"]
@dataclass(frozen=True)
class ValidationFinding:
    validator: str                       # "page_budget"
    severity: Severity                   # gates when "block"
    code: str                            # "over_page_limit", "self_citation_leak", ...
    message: str
    locator: dict = field(default_factory=dict)
@dataclass(frozen=True)
class CompilePageInfo:
    page_count: int | None               # None => could not measure (fail closed)
    measured_by: str                     # "pdf" | "unavailable"
    detail: str = ""
@dataclass(frozen=True)
class ComplianceContext:
    document: "ThesisDocument"
    sources: dict
    page_info: CompilePageInfo
    profile: "DomainProfile"
class ProfileValidator(Protocol):
    key: str
    def validate(self, ctx: ComplianceContext) -> list[ValidationFinding]: ...

# app/domains/profiles.py
@dataclass(frozen=True)
class DomainProfile:
    ...
    submission_checklist: tuple[str, ...]
    validators: tuple[str, ...] = ()     # NEW
    page_limit: int | None = None        # NEW
    def enforces(self) -> bool: return bool(self.validators)
```

### Core algorithm / flow
`run_profile(profile, ctx)` iterates `profile.validators`, resolves via `get_validator`, concatenates findings; `ready = not any(f.severity == "block" ...)`.
1. **PageBudgetValidator** — measurement from the compiled output, not an estimate. Render canonical → DOCX via `render_docx(doc_model, sources, profile, output_path)`, convert with `pdf_renderer.convert_to_pdf` (LibreOffice headless), count PDF pages. `page_count > profile.page_limit` → `block` `over_page_limit`. References excluded per venue convention via section-order boundary. `measured_by == "unavailable"` (no soffice) → `block` `page_count_unmeasurable` (fail closed).
2. **DoubleBlindValidator** — heuristic lint over canonical blocks (walks `front_matter` + `chapters[*].blocks`, text from `ParagraphBlock.runs`/`HeadingBlock.text`/`BlockQuoteBlock.text`): acknowledgement/funding front-matter or regex (`funding`, `grant no`, `we thank`) → `warn`/`block`; identity-leaking self-citation (author surname vs `meta.candidate.name` + `\b(our|we|my)\s+(previous|prior)\s+work\b`) → `warn`; non-anonymized links (`github\.com/…`, ORCID, emails) not on an anonymized-host allowlist (`anonymous.4open.science`, `osf.io/anonymous`) → `block` `deanonymizing_link`.
3. **ReproducibilityChecklistValidator** — maps reproducibility `submission_checklist` items to machine checks: the `reproducibility_checklist` section must exist and be non-empty, and structured answers in `project.meta["reproducibility"]` (item→yes/no/na+justification) must be fully answered. Unanswered → `block` `reproducibility_incomplete`. Turns advisory checklist strings into enforced findings.
4. **Camera-ready** (`camera_ready.py`) — not a validator; resolves a venue's deterministic formatting into the existing `ResolvedProfile` consumed by `render_docx`, reusing `pagination.py`. Same canonical input → byte-stable DOCX.

### API endpoints
Add to the existing `app/api/domain_profiles.py` router.
`GET /projects/{project_id}/compliance` — run the profile's validators against the current snapshot (uses `project.meta["domain_profile"]`, like `domain-readiness`).
```json
{"profile":"neurips_paper","enforced":true,"ready":false,
 "page":{"page_count":11,"limit":9,"measured_by":"pdf"},
 "findings":[
   {"validator":"page_budget","severity":"block","code":"over_page_limit","message":"Compiled body is 11 pages; NeurIPS limit is 9.","locator":{"page_count":11,"limit":9}},
   {"validator":"double_blind","severity":"block","code":"deanonymizing_link","message":"Non-anonymized repository link in Section 4.","locator":{"block_id":"…","match":"github.com/…"}}],
 "checklist":["NeurIPS checklist completed","Within the venue page limit","..."]}
```
No profile / `validators=()` → soft `{"profile":null|key,"enforced":false,"ready":true,"findings":[]}` — never a hard 4xx (advisory-by-default, gating only on venue profiles). Optional `POST /projects/{project_id}/camera-ready` → 202, emits a camera-ready DOCX/PDF.

### Integration seams
- `app/domains/profiles.py` — add `validators`/`page_limit`; populate on the three venue profiles; `available_domain_profiles()`/`get_domain_profile_detail` expose them.
- `app/api/domain_profiles.py` — new `/compliance` route beside `project_domain_readiness`; identical `fetch_owned_project` + `get_domain_profile` + `UnknownDomainProfile` plumbing.
- Compile path — the compliance service calls canonical `render_docx` (not the quarantined `LEGACY_COMPILE` chat pipeline) + `pdf_renderer.convert_to_pdf`.
- Submission — `app/collaboration/sealing.py::submission_readiness`/`seal_submission` call `run_profile(...)`; a `block` finding becomes a `SubmissionError`/blocking dimension, wiring enforcement into `POST /projects/{id}/submission-packages`.
- Canonical model — validators read `ThesisDocument` (`front_matter[*].kind`, `chapters[*].blocks`, `meta.ai_disclosure`, `meta.candidate`); no model changes.

### External dependencies & fail-closed behavior
Page counting needs the rendered artifact → depends on the LibreOffice/`soffice` PDF stack (`app/renderers/pdf_renderer.py`, `SofficeUnavailableError`, `check_pdf_stack()`). The compliance service catches `SofficeUnavailableError`/`PdfConversionError` → `CompilePageInfo(page_count=None, measured_by="unavailable")` → `PageBudgetValidator` emits a `block` rather than passing silently. Anonymization + reproducibility validators are pure-Python (regex + dict lookups), no external deps, always run. `render_docx` raising `RenderError` on unresolved works-cited surfaces as a `block` (not compilable ⇒ not submission-ready).

### Test plan
- `tests/test_domain_validators_page_budget.py` — 11 pages → block; 9 → clean; `unavailable` → `page_count_unmeasurable` block (monkeypatch `convert_to_pdf` to raise).
- `tests/test_domain_validators_anonymization.py` — `github.com/user/repo` → block; acknowledgement present → block; `"our previous work [3]"` self-cite → warn; anonymized link → no finding; funding line → warn.
- `tests/test_domain_validators_reproducibility.py` — empty checklist → block; fully answered → clean; partial → item locator.
- `tests/test_domain_profiles_registry.py` — every `validators` key resolves; non-venue `validators=()`; detail exposes new fields.
- `tests/test_compliance_api.py` — NeurIPS project `enforced=true` with findings; no-profile soft `ready=true`; cross-user → 404.
- `tests/test_submission_gating.py` — seal blocked while a `block` finding exists; unblocks once resolved.

### Effort, risk, dependencies
- **PageBudgetValidator — M.** Depends on PDF stack + canonical `render_docx`. Risk: LibreOffice page count vs venue LaTeX template differs; mitigate by measuring the deterministic camera-ready render, fail-closed when unmeasurable.
- **DoubleBlindValidator — S/M.** Independent, pure-Python, highest immediate value. Risk: heuristic precision (false positives) — `warn` for ambiguous, `block` only for unambiguous leaks; allowlist anonymized hosts.
- **ReproducibilityChecklistValidator — S.** Independent; small `project.meta["reproducibility"]` store (no migration). Risk: keeping item text synced with the venue's official list.
- **Camera-ready — M/L.** Reuses `ResolvedProfile`/`pagination.py`. Risk: matching each venue's template deterministically is detail-heavy; ship per-venue.
The two pure validators (anonymization, reproducibility) need no compile output and can ship first. No integrity-core changes; all four land in the profiles/domain-readiness/compile seams.

---

## 3.5 Interoperability and deposit

### Overview
Closes the loop from a canonical `ThesisDocument` to a citable published artifact. Adds two pure renderers/importers alongside `latex`/`csl`/`bibtex`/`ris` (`jats.py` export, `latex_import.py` import), an ORCID identity client, and an outbound *deposit* integration (Zenodo/DSpace) behind a small adapter that mints a DOI and records external state in a new `deposits` table. Import paths follow the established discipline — never invent bibliographic data, fail closed on anything unsupported.

### Data model & migrations
JATS export and LaTeX import are **stateless** (JATS reuses `run_export`; LaTeX import writes to existing `Project`/`Source` like `references_import`) — no schema change. Deposit + ORCID need one new table + `User` columns.

New model `app/models/deposit.py` → table `deposits`: `id` PK; `project_id` FK CASCADE index; `user_id` FK CASCADE index; `export_id` FK `exports.id` SET NULL nullable; `repository` `String(20)` (`zenodo|dspace`); `status` `String(20)` default `pending` (`pending`→`draft_created`→`files_uploaded`→`published|failed`); `external_id` `String(200)` nullable; `doi` `String(120)` nullable; `concept_doi` `String(120)` nullable; `orcid` `String(19)` nullable; `landing_url` `String(500)` nullable; `sandbox` Boolean default True; `error_message` Text nullable; `response` JSONB nullable; `created_at`/`updated_at`. Indexes: `ix_deposits_project_status (project_id, status)`; partial unique `uq_deposits_project_repo_active (project_id, repository) WHERE status NOT IN ('failed')`.

ORCID linkage on `User` — add nullable `orcid String(19)` + `orcid_verified_at DateTime(tz)` (denormalized copy onto `deposits.orcid` at deposit time).

**Migration** (`down_revision="0021"`): `op.add_column("users", orcid/orcid_verified_at)`; `op.create_table("deposits", ...)` + the two indexes (partial unique via `postgresql_where=sa.text("status NOT IN ('failed')")`). **Duplicate-column trap:** confirm no earlier migration added `users.orcid` (grep shows none through 0021); `deposits.orcid` is a different table, no conflict. Bump `Settings.SCHEMA_VERSION`.

### Module layout
```
app/renderers/jats.py            # to_jats(doc, sources) -> str   (pure, mirrors latex.py)
app/importers/latex_import.py    # from_latex(text) -> ThesisDocument ; UnsupportedLatexError
app/importers/docx_tracked.py    # from_docx_tracked(path) -> ThesisDocument (w:ins/w:del)
app/importers/csl_import.py      # from_csl_json(items) -> list[dict] (source candidates)
app/integrations/orcid.py        # OrcidClient (OAuth + public API)
app/integrations/deposit/base.py     # DepositTarget Protocol, DepositError, DepositResult
app/integrations/deposit/zenodo.py   # ZenodoTarget
app/integrations/deposit/dspace.py   # DSpaceTarget
app/services/deposit_service.py  # orchestration + Deposit row lifecycle
app/api/deposits.py              # REST (deposit + orcid link)
```

### Key interfaces & signatures
```python
# app/renderers/jats.py — same shape as to_latex
def to_jats(doc: ThesisDocument, sources: dict[Any, SourceLike]) -> str: ...

# app/importers/latex_import.py
class UnsupportedLatexError(ValueError):
    """A macro/environment outside the supported subset was encountered."""
def from_latex(text: str) -> ThesisDocument:
    """Parse a LaTeX article-subset into canonical. Fails closed on unsupported
    macros; never fabricates metadata."""

# app/integrations/deposit/base.py
@dataclass
class DepositResult:
    external_id: str
    doi: str | None
    concept_doi: str | None
    landing_url: str | None
    raw: dict
class DepositError(RuntimeError): ...
class DepositTarget(Protocol):
    name: str                                   # "zenodo" | "dspace"
    async def create_draft(self, meta: "DepositMeta") -> str: ...          # -> external_id
    async def upload_file(self, external_id: str, path: str, filename: str) -> None: ...
    async def publish(self, external_id: str) -> DepositResult: ...          # mints DOI

# app/integrations/orcid.py
class OrcidClient:
    def authorize_url(self, state: str, redirect_uri: str) -> str: ...
    async def exchange_code(self, code: str, redirect_uri: str) -> "OrcidToken": ...  # -> orcid + name
    async def verify_orcid(self, orcid: str) -> bool: ...
```
JATS reuses `SourceLike.fields` and simply *omits* absent fields (like `to_latex`/`to_csl_json`) — it is a data serializer, not a `_require`-formatted style. Import mirrors `from_bibtex`: map only present fields.

### Core algorithm / flow
**JATS export (`to_jats`)** — walk canonical, deterministic like `to_latex`: `<article>`→`<front>` from `doc.meta` (`<article-title>`, `<contrib-group>` from `meta.candidate.name`, `<contrib-id contrib-id-type="orcid">` if `User.orcid`); `<body>` maps `ChapterDoc`→`<sec><title>`, `ParagraphBlock`→`<p>` (`Run(italic)`→`<italic>`), `BlockQuoteBlock`→`<disp-quote>`, `MarkerBlock`→ **abort** (`RenderError`, reusing the unresolved-marker export rule); `<back><ref-list>` from `WorksCitedRef`→`<element-citation>` with `<pub-id pub-id-type="doi">`. All text XML-escaped via a new `_xml_escape` (analogue of `escape_latex`).

**LaTeX import (`from_latex`)** — supported subset only, fail closed: read `\title{}`/`\author{}` into `ThesisMeta`/`CandidateMeta`; `\section`→`ChapterDoc`, `\subsection`→`HeadingBlock(level=2)`; blank-line-separated → `ParagraphBlock`; `\textit`/`\emph`→`Run(italic=True)`; `\begin{quote}`→`BlockQuoteBlock`; `\cite{key}` → **not** a fabricated `WorksCitedRef` but a `MarkerBlock(kind="SOURCE_NEEDED")` recording the unresolved key. Any control sequence outside the whitelist (`\includegraphics`, `\input`, `\newcommand`, unknown env) → `UnsupportedLatexError` naming the macro; API returns 422; nothing partial is written.

**Deposit handshake + DOI mint** (`deposit_service.initiate_deposit`): require a ready final `Export`; create `Deposit(status="pending")`; resolve `DepositTarget`; `create_draft` → `draft_created`; download artifact from storage → `upload_file` → `files_uploaded`; `publish` → mints DOI → persist `doi`/`concept_doi`/`landing_url`/`response`, status `published`. Any exception → `failed`, `error_message` set, nothing left half-published (drafts stay unpublished until `publish`).

### API endpoints
- **Export JATS** — widen `EXPORT_FORMATS` to include `"jats"` (media type `application/jats+xml`); existing `POST /projects/{id}/exports {"formats":["jats"]}` + `GET /exports/{id}/download` already work; `run_export` gains a `jats` branch.
- **Import LaTeX** — `POST /projects/{project_id}/import/latex` `{"content":"<latex>"}` (2 MB cap) → `{"chapters":3,"paragraphs":41,"unresolved_citations":2,"unsupported":null}` or 422 `{"detail":"Unsupported macro \\includegraphics"}`.
- **Import CSL-JSON** — `POST /projects/{project_id}/references/import {"format":"csl","content":"[...]"}` → `{"imported":12,"kinds":{"journal":9,"book":3}}`.
- **Deposit** — `POST /projects/{project_id}/deposits {"repository":"zenodo","export_id":"<uuid>","sandbox":true}` → `{"deposit_id":"<uuid>","status":"pending"}`; `GET /projects/{project_id}/deposits/{deposit_id}` → `{"status":"published","doi":"10.5281/zenodo.12345","landing_url":"...","repository":"zenodo"}`.
- **ORCID** — `GET /me/orcid/authorize` → `{"authorize_url":"..."}`; `POST /me/orcid/callback {"code":"...","state":"..."}` → `{"orcid":"0000-0002-1825-0097","verified":true}`; `DELETE /me/orcid` → 204.

### Integration seams
- `app/services/export_service.py`: add `"jats"` to `EXPORT_FORMATS`/`MEDIA_TYPES` and a dispatch branch `_write_text(output_path, to_jats(document, sources))`; `build_thesis_document` + `sources` dict feed both JATS and deposit unchanged.
- `app/api/projects.py`: `EXPORT_FORMATS`/`MEDIA_TYPES` import + format-validation automatically accept `jats`; download route serves it.
- `app/canonical/model.py` constructors: `from_latex` builds `ThesisDocument`/`ChapterDoc`/`ParagraphBlock(runs=[Run(...)])`/`HeadingBlock`/`BlockQuoteBlock`/`MarkerBlock`/`ThesisMeta`/`CandidateMeta` — the classes `test_latex.py` uses.
- `app/renderers/latex.py`: `from_latex` inverts `escape_latex`'s `_LATEX_SPECIALS`; `to_jats` copies `_block_latex`/`_bibliography`/`SourceLike` resolution shape.
- `app/renderers/csl.py`: `from_csl_json` inverts `_CSL_TYPE`/`_parse_authors`, feeding `references_import.import_references`.
- `app/models/source.py`: imports insert `Source(parse_status="imported", verified=False)`.
- `app/ingest/docx_extract.py` + `python-docx` (already a dep): `from_docx_tracked` reads `w:ins`/`w:del`.

### External dependencies & fail-closed behavior
LaTeX parsing: `pylatexenc`/`TexSoup` are **not** in requirements. Prefer `pylatexenc` (`LatexWalker` node tree, ideal for whitelist-and-fail-closed); or a custom brace-matching tokenizer in the `bibtex_import._parse_fields` style. Unsupported macros raise `UnsupportedLatexError` → 422; never a partial doc. HTTP: reuse `httpx` (present) with injected `AsyncClient`. New credential settings (default `""`): `ZENODO_TOKEN`/`ZENODO_SANDBOX_TOKEN`/`ZENODO_BASE_URL`, `DSPACE_*`, `ORCID_CLIENT_ID`/`ORCID_CLIENT_SECRET`/`ORCID_BASE_URL`. **Fail closed:** empty token → `Deposit.status="failed"`, `error_message="… credentials not configured"`, 503/422, no network call, no half-created draft; sandbox is default so a misconfig cannot publish to production Zenodo. JATS export refuses documents containing `MarkerBlock`s (unresolved-marker rule).

### Test plan
- `tests/test_jats.py` — smoke mirroring `test_latex.py`: `<article`/`<article-title>`/`<sec>`/`<italic>`/`<ref-list>`/`<pub-id …doi>` present; well-formed via `ElementTree.fromstring`; `MarkerBlock` doc → `RenderError`; `_xml_escape` handles `&<>`.
- `tests/test_latex_import.py` — `from_latex(to_latex(doc, sources))` round-trip preserves chapter titles/text/italic; `\includegraphics{x}` → `UnsupportedLatexError`; `\cite{foo}` → `SOURCE_NEEDED` marker; unbalanced braces fail closed; `\&`→`&`.
- `tests/test_csl_import.py` — `from_csl_json(to_csl_json(sources))` round-trip; unknown type fallback; missing fields dropped.
- `tests/test_deposit_service.py` — faked `DepositTarget` asserts `create_draft→upload_file→publish` order + status transitions; publish exception → `failed`+`error_message`, no DOI.
- `tests/test_zenodo_adapter.py` — `httpx.MockTransport` canned payloads; DOI parsed; missing token → `DepositError`, no request sent.
- `tests/test_orcid.py` — `MockTransport` token exchange + verify; `authorize_url` contains client id/state; missing secret → `OrcidError`.
- `tests/test_deposits_api.py` + `tests/test_import_api.py` — owner guard (404), 2 MB cap, poll shape, dual-mount.

### Effort, risk, dependencies
JATS export **S–M** (pure renderer); LaTeX import **M** (inherently lossy — subset + fail-closed contain it); CSL import **S**; DOCX tracked-changes **M**; ORCID **S–M** (OAuth); deposit adapters + service + table + migration **M–L** (partner-dependent: credentials, sandbox flakiness, DSpace REST drift). JATS/LaTeX/CSL/DOCX import need no partner accounts and ship first. The `deposits` table + `run_export` `jats` branch are the only changes touching shared write paths; everything else is additive modules mirroring existing renderer/importer patterns.

---

## 3.6 Supervision and committee workflow

### Overview
Adds advisor/committee roles with scoped permissions on top of the existing capability model (`app/collaboration/capabilities.py`), block-anchored feedback keyed to `BlockIdentity.id` (surviving re-render because the anchor is the canonical block UUID, not a text offset), meaning-level diffing between two `DocumentSnapshot` payloads, and a read-only defense/viva prep bundle. Extends `collaboration/workflow.py` and reuses `DocumentSnapshot.canonical_document` as the diff substrate. The sensitive surface — who may see content vs metadata, comment vs approve vs seal — is expressed entirely as capability sets resolved through the existing `resolve_project_access` seam, keeping the deferred institution-scoped authz decision in one place.

### Data model & migrations
Three new tables plus one additive column. All UUID PKs, `JSONB` payloads, `DateTime(tz)` timestamps, mirroring `app/models/tenancy.py`.

**`committee_memberships`** — advisor/committee seat, refining supervisor-class `project_memberships` into committee positions: `id`; `project_id` FK CASCADE; `user_id` FK CASCADE; `project_membership_id` FK SET NULL nullable; `committee_role` `String(32)`; `position` Integer default 0; `voting` Boolean default false; `content_access` Boolean default true; `status` `String(24)` default `active`; `assigned_by` FK RESTRICT; timestamps. `UniqueConstraint(project_id, user_id)`; indexes on `(project_id, committee_role, status)` and `(user_id, status)`.

**`block_comments`** — feedback anchored to block identity, deliberately separate from the offset-based `collaboration_comments` (which drifts): `id`; `project_id` FK CASCADE; `canonical_block_id` UUID **not** an FK (block identity lives in JSONB); `scope_type` `String(24)`; `scope_id` UUID nullable; `thread_root_id` self-FK CASCADE nullable; `author_id` FK RESTRICT; `committee_role` `String(32)` nullable (denormalized at write); `body` Text; `block_text_snapshot` Text nullable (drift detection); `first_seen_document_version` Integer; `anchor_state` `String(24)` default `current` (`current|block_changed|orphaned`); `visibility` `String(30)` default `committee` (`committee|student_supervisor|private_author`); `status` `String(24)` default `open`; `resolved_by`/`resolved_at`; timestamps. Indexes on `(project_id, canonical_block_id, status)`, `(thread_root_id, created_at)`, `(project_id, status, created_at)`.

**`semantic_draft_diffs`** — cached meaning-level diff keyed by ordered snapshot pair: `id`; `project_id` FK CASCADE; `base_snapshot_id`/`head_snapshot_id` FK `document_snapshots.id` RESTRICT; `base_document_version`/`head_document_version` Integer; `summary` JSONB; `entries` JSONB; `computed_by` FK SET NULL nullable; `created_at`. `UniqueConstraint(base_snapshot_id, head_snapshot_id)`.

**Additive column:** `projects.defense_state String(24) NOT NULL SERVER_DEFAULT 'not_scheduled'` — composes with the existing `workflow_state` machine without altering `WORKFLOW_TRANSITIONS`.

**Migration** (`down_revision="0021"`), model-driven create like `0012`/`0015`/`0017`:
```python
from app.db.session import Base
import app.models  # noqa: F401
_TABLES_IN_ORDER = ["committee_memberships", "block_comments", "semantic_draft_diffs"]
def upgrade():
    for name in _TABLES_IN_ORDER:
        Base.metadata.tables[name].create(op.get_bind(), checkfirst=True)
    op.add_column("projects", sa.Column("defense_state", sa.String(24), nullable=False, server_default="not_scheduled"))
def downgrade():
    op.drop_column("projects", "defense_state")
    for name in reversed(_TABLES_IN_ORDER):
        Base.metadata.tables[name].drop(op.get_bind(), checkfirst=True)
```
**Duplicate-column note:** create **only** the three new tables by name — never `create_all` (it would recreate live tables). Because `block_comments`/`collaboration_comments` share concept-columns, do not also `op.add_column` these onto the old table. `defense_state` uses a scalar `server_default` string literal (not a JSON `sa.text` token), matching the `0012` `workflow_state` precedent; `checkfirst=True` keeps it idempotent.

### Key interfaces & signatures
```python
# app/collaboration/committee.py
class CommitteeRole(StrEnum):
    STUDENT="student"; ADVISOR="advisor"; CO_ADVISOR="co_advisor"
    COMMITTEE_MEMBER="committee_member"; INTERNAL_EXAMINER="internal_examiner"
    EXTERNAL_EXAMINER="external_examiner"; CHAIR="chair"
class SupervisionPermission(StrEnum):
    VIEW_CONTENT="supervision.view_content"; VIEW_SOURCES="supervision.view_sources"
    COMMENT="supervision.comment"; RESOLVE_OWN="supervision.resolve_own"; RESOLVE_ANY="supervision.resolve_any"
    VIEW_DIFF="supervision.view_diff"; APPROVE_CHAPTER="supervision.approve_chapter"
    APPROVE_ACADEMIC="supervision.approve_academic"; ASSIGN_COMMITTEE="supervision.assign_committee"
    VIEW_DEFENSE="supervision.view_defense"
COMMITTEE_PERMISSIONS: dict[CommitteeRole, frozenset[SupervisionPermission]]   # closed, deny-by-default
def committee_permissions(role) -> frozenset: return COMMITTEE_PERMISSIONS.get(role, frozenset())
async def require_committee_permission(db, project_id, user, permission) -> "CommitteeContext": ...
    # 404 (not 403) on failure, matching require_project_capability's non-enumeration policy.

# app/collaboration/semantic_diff.py
ChangeClass = Literal["added","removed","moved","meaning_changed","formatting_only","unchanged"]
@dataclass(frozen=True)
class BlockDiffEntry:
    block_id: UUID; change: ChangeClass
    base_location: tuple[UUID, int] | None; head_location: tuple[UUID, int] | None
    base_signature: str | None; head_signature: str | None
@dataclass(frozen=True)
class DiffResult:
    entries: list[BlockDiffEntry]; summary: dict[ChangeClass, int]
def block_semantic_signature(block: Block) -> str:
    """Meaning-normalised hash: lowercased, whitespace-collapsed text with run
    italics/formatting and citation punctuation stripped. Reuses workflow.block_text."""
def semantic_diff(base: ThesisDocument, head: ThesisDocument) -> DiffResult:
    """Match blocks by BlockIdentity.id across chapters + front_matter, classify each."""
```

### Core algorithm / flow
1. **Comment anchoring survives re-render.** On create, client sends `canonical_block_id`. `create_block_comment` calls `find_block` (reused from `workflow.py`), rejects unknown ids, stores `block_text_snapshot` + `first_seen_document_version`. The persisted anchor is the *UUID only* — no offsets. Renderers consume the same canonical doc and never mutate block ids, so re-render/re-style/re-paginate cannot move the anchor. On read, `refresh_block_anchor` re-runs `find_block`: id present + text equal → `current`; id present, text differs → `block_changed`; id absent → `orphaned`. Strictly stronger than the offset-based `refresh_comment_anchor`.
2. **Permission check (deny-by-default).** Every endpoint funnels through `require_committee_permission`: `resolve_project_access(db, project_id, user)` (existing) → `None` = 404; owner (student) gets comment/resolve-own/view/diff/defense, never approve/assign; else load active `CommitteeMembership`, map `committee_role`→permissions, then **intersect** with `ProjectAccess.capabilities` (a metadata-only admin cannot gain `VIEW_CONTENT`; `content_access=false` strips content reads). This layer can only *narrow*, never *widen*. Whole-thesis sealing is gated on `APPROVE_ACADEMIC`, which committee members/examiners do not hold; the seal transition still runs through the unchanged `decide_review`/`transition_project` capability gate — this layer adds a check, never bypasses one. Permission absent from the closed table → 404.
3. **Semantic diff.** Both `DocumentSnapshot.canonical_document` payloads `model_validate`'d; build `dict[UUID, (scope_id, position, Block)]` by walking `front_matter` then `chapters`. `head not in base`→`added`; `base not in head`→`removed`; both: compare `block_semantic_signature` — equal + same location → `unchanged`; equal + moved → `moved`; signatures differ but only whitespace/italics/citation-punctuation differs → `formatting_only`; signatures differ → `meaning_changed` (reword "X causes Y"→"X may correlate with Y" changes normalized tokens, so the signature diverges where a line-diff shows just an edit). Persist keyed by `(base_snapshot_id, head_snapshot_id)` — immutable snapshots → cacheable forever.
4. **Defense bundle.** `build_defense_bundle` walks the approved doc: `MarkerBlock`s of kind `EVIDENCE_NEEDED`/`VERIFY` as open items, `BlockQuoteBlock`/`VerseQuoteBlock` + `quote_id`→verified-source join, `works_cited`→source metadata, headings as panel outline. Read-only.

### API endpoints
- `POST /projects/{project_id}/committee` (perm `ASSIGN_COMMITTEE`) `{"user_id":"...","committee_role":"advisor","voting":true,"content_access":true,"position":1}` → 201.
- `GET /projects/{project_id}/committee` → `{"members":[...]}`.
- `PATCH /projects/{project_id}/committee/{membership_id}` `{"status":"withdrawn"}|{"committee_role":"chair"}` → 200.
- `POST /projects/{project_id}/block-comments` (perm `COMMENT`) `{"canonical_block_id":"...","scope_type":"chapter","scope_id":"...","body":"...","thread_root_id":null,"visibility":"committee"}` → 201.
- `GET /projects/{project_id}/block-comments?block_id=&status=open` → each row's `anchor_state` recomputed.
- `PATCH /projects/{project_id}/block-comments/{comment_id}` `{"action":"resolve"}` — `RESOLVE_ANY`, or `RESOLVE_OWN` when author.
- `DELETE /projects/{project_id}/block-comments/{comment_id}` — author or `RESOLVE_ANY`.
- `GET /projects/{project_id}/diff?base_snapshot_id=&head_snapshot_id=` (perm `VIEW_DIFF`) → `{"summary":{"added":2,"removed":1,"moved":3,"meaning_changed":5,"formatting_only":4,"unchanged":120},"entries":[...]}`.
- `GET /projects/{project_id}/defense-prep` (perm `VIEW_DEFENSE`) → outline/claims/quotes/open_markers/committee.
- `POST /projects/{project_id}/defense-prep/state` (perm `ASSIGN_COMMITTEE`) `{"target":"scheduled"}`.

### Integration seams
- `app/collaboration/capabilities.py::resolve_project_access` — the single authoritative "who is this user on this project"; `require_committee_permission` composes on top and can only intersect down. No new coarse role — committee seats reuse `supervisor`/`external_reviewer` project roles, refined by `committee_memberships`.
- `app/collaboration/workflow.py` — reuse `find_block`, `block_text`, `_document`, `canonical_checksum` for anchoring/diffing. Academic sign-off continues through `decide_review`/`transition_project`; `APPROVE_ACADEMIC` is an additional gate, not a replacement for the `project.approve_academic` check.
- `app/api/deps.py::CurrentUser`/`fetch_owned_project` — owner short-circuit in `resolve_project_access` covers the student-author path.
- `app/canonical/model.py::BlockIdentity` — `.id` is the comment anchor + diff key; depends only on the existing id-stability guarantee from the Phase 2 command layer.
- `app/models/document_snapshot.py::canonical_document` — the immutable diff substrate; `ReviewCycle.snapshot_id` gives natural draft endpoints.
- `app/api/institutional_lifecycle.py`/`require_institution_capability` — **the deferred institution-scoped authz**: keep the boundary where it already is. `ASSIGN_COMMITTEE` requires the actor to already hold project authority via `resolve_project_access` (whose admin branch is gated on a *verified* `OrganizationMembership` matching the project's `institution_id`). No parallel institution grant path; an external examiner from another institution is an explicit per-project seat, never inferred from a home-institution admin role — confining the cross-institution decision to one reviewed insertion point.

### External dependencies & fail-closed behavior
No new dependencies. `COMMITTEE_PERMISSIONS` is a closed dict → unknown role grants `frozenset()`. `require_committee_permission` raises 404 (not 403) on no-access / no-membership / missing-permission — never a permissive default, and 404 avoids project-existence enumeration. Committee permissions are intersected with `ProjectAccess.capabilities`, so a seat can never grant more than the project layer allows; `content_access=false` strips content/source reads. `create_block_comment` rejects any `canonical_block_id` not in the current document (no fabricated anchors).

### Test plan
- `tests/test_committee_permissions.py` — table-driven per role; advisor has `APPROVE_ACADEMIC`, committee member does not; unknown role → empty; non-member → 404; `content_access=false` strips `VIEW_CONTENT`.
- `tests/test_committee_authz_composition.py` — metadata-only admin cannot gain `VIEW_CONTENT` via a seat; external examiner is sealed-only; seat cannot widen a `content_access=false` membership; cross-institution no-seat → 404.
- `tests/test_block_comment_anchor.py` — comment stays `current` across re-render/re-style; edit block text → `block_changed`; delete block → `orphaned`; no offsets stored.
- `tests/test_block_comment_crud.py` — thread replies; author resolves own; non-author needs `RESOLVE_ANY`; visibility filtering.
- `tests/test_semantic_diff.py` — reword → `meaning_changed`; italics/whitespace/citation-punct only → `formatting_only` (not meaning_changed); move → `moved`; insert/delete → added/removed; identical → all unchanged; cached result re-served.
- `tests/test_defense_prep.py` — bundle collects markers/quotes/outline/roster; advisor can seal, plain committee member cannot.
- `tests/test_migration_supervision.py` — upgrade/downgrade round-trip; three tables + `defense_state` created once (idempotent with `checkfirst`); default `not_scheduled`.

### Effort, risk, dependencies
**M.** Three tables + one column, one migration, four service modules, one router. The diff normalization and permission-composition matrix are the only non-mechanical parts; everything reuses `find_block`/`resolve_project_access`/`DocumentSnapshot`. **Risks:** authz composition is load-bearing (a regression letting a seat *widen* access is the primary failure mode — mitigated by composition tests + 404-on-deny); privacy regime (visibility + metadata-only members must honor the content/metadata split); semantic-diff calibration is heuristic (advisory; raw text diff remains available); block-id stability is assumed from Phase 2 (worth an editor-service invariant test). **Dependencies:** Phase 4 collaborative workspace (`0012`–`0015`) at head `0021`; the `BlockIdentity` id-stability guarantee; the `resolve_project_access` verified-affiliation gate. The deferred institution-scoped authz is *addressed by scoping around it*, not resolved.

---

## 3.7 Multilingual and non-English scholarship

### Overview
Acadensia already separates citation *mechanism* from *text* (styles emit canonical `Run` lists, not strings) and resolves fields under a never-guess discipline — the exact seam a locale layer plugs into. This direction adds a `locale` dimension to the citation-style registry, a fail-closed transliteration helper for author names, and directionality/script awareness in the run-emitting renderers, without reopening the integrity core. It rides the existing `ThesisMeta` JSON blob for storage, so no SQL column change is strictly required.

### Data model & migrations
Locale is a document-level property beside `citation_style` on `ThesisMeta`:
```python
class ThesisMeta(BaseModel):
    ...
    citation_style: str = "mla-9"
    domain_profile: str = ""
    locale: str = ""            # BCP-47, e.g. "ar", "zh-Hans", "de-DE", "fa-IR" ("" == en, unchanged)
    name_script: Literal["source", "translit", "both"] = "source"
```
`ThesisMeta` serializes whole into `projects.meta` (JSONB), so a new optional field with a default deserializes cleanly from every existing row — **no migration needed for storage**, the same pattern by which `citation_style`/`domain_profile` were added. A migration (adding `projects.locale String(35)`) is warranted **only** if locale must be queried/filtered at the SQL layer. **Duplicate-column trap:** if added, `meta.locale` (canonical, source of truth) and a `projects.locale` column (queryable projection) must not both be authoritative — the column is populated read-only from `meta.locale` on save; never let an endpoint update it independently, or exports (read `meta`) and queries (read the column) diverge.

### Module layout
Keep locale concerns out of the integrity core, inside the renderer/styles seam:
```
app/renderers/locale/
    __init__.py            # resolve_locale(), locale registry (BCP-47 -> LocaleProfile)
    profile.py             # LocaleProfile: name_order, punctuation, direction, collation, digit shaping
    transliterate.py       # transliterate_name() + fail-closed policy
    typography.py          # locale punctuation maps (CJK full-width, «» guillemets, Arabic ، )
    directionality.py      # script detection + RTL/CJK run-emission helpers
    templates/             # per-language submission/front-matter template strings (ar.py, zh.py, ...)
```
Locale-specific citation *variants* stay as thin subclasses in `app/renderers/styles/` (e.g. `din1505.py` German DIN 1505-2, `gb7714.py` Chinese national standard), registered alongside the current 14. Locale-generic behavior (punctuation swap, name order) is applied by the `locale/` layer wrapping any style; a full locale *style* is written only when ordering/structure itself differs.

### Key interfaces & signatures
`CitationStyle` (Protocol in `base.py`) gains an optional, backward-compatible `locale` param — existing styles satisfy it unchanged:
```python
# app/renderers/styles/base.py
class CitationStyle(Protocol):
    key: str; edition: str; mechanism: CitationMechanism
    def required_fields(self, source_type: str) -> tuple[str, ...]: ...
    def format_reference(self, source: SourceLike, ordinal: int | None = None,
                         locale: "LocaleProfile | None" = None) -> list[Run]: ...
    def sorted_entries(self, sources: list[SourceLike],
                       locale: "LocaleProfile | None" = None) -> list[list[Run]]: ...

# app/renderers/locale/profile.py
@dataclass(frozen=True)
class LocaleProfile:
    tag: str                 # "zh-Hans"
    direction: Literal["ltr", "rtl"]
    name_order: Literal["given_family", "family_given", "family_given_nocomma"]
    quote_open: str; quote_close: str
    list_sep: str            # ", " vs "、" vs "، "
    collation: str           # ICU collation key, e.g. "zh@collation=pinyin"
def resolve_locale(tag: str | None) -> LocaleProfile | None:  # "" / None -> None (English)

# app/renderers/locale/transliterate.py
class Transliteration(NamedTuple):
    text: str
    certain: bool            # False -> caller must fail closed to source script
def transliterate_name(name: str, target: str) -> Transliteration:
    """Romanize toward target script. certain=False when ambiguous/unsupported;
    NEVER silently emits a guessed romanization."""

# app/renderers/locale/directionality.py
def script_of(text: str) -> Literal["latin","arabic","hebrew","han","kana","mixed"]
def emit_directional_runs(runs: list[Run], profile: LocaleProfile) -> list[Run]:
    """Wrap RTL / mixed spans with U+2068 FSI ... U+2069 PDI so a Latin DOI inside
    an Arabic entry does not reorder. LTR/None -> runs unchanged."""
```
Because output is always `Run(text, italic)`, directionality is expressed as Unicode isolate characters embedded in `Run.text` (portable to md/txt/docx) plus a paragraph-level RTL flag consumed only by the docx renderer — the `Run` model does not change.

### Core algorithm / flow
1. **Resolve once per render.** `render_md`/`render_docx` call `profile = resolve_locale(doc.meta.locale)`; empty/`None` short-circuits to today's exact English path (regression-proof).
2. **Style selection.** `get_citation_style(doc.meta.citation_style)` as today; the `LocaleProfile` is threaded into `sorted_entries(..., locale=profile)`. A locale-specific style key (`gb7714-2015`) may itself be the selected style; orthogonal.
3. **Locale ordering.** `sorted_entries` replaces the ASCII `_sort_key` (`works_cited.py`) with a collation-aware key from `profile.collation` (ICU) when present — 陈 sorts by Pinyin, Arabic names by normalized form — falling back to `_sort_key` for English. Numbered mechanisms (IEEE) keep order-of-appearance.
4. **Locale punctuation.** Separators/quotes drawn from `profile` instead of hard-coded `“…”`, `, ` — CJK `、` + full-width, German `„…“`, French `«… »` — as a post-pass over the produced `Run` list so each concrete style stays readable and English is untouched.
5. **Author transliteration.** Per `meta.name_script`: `source` = stored string verbatim (today); `translit`/`both` call `transliterate_name`. **Never-guess:** `certain is False` → do not invent a romanization; fall back to source script (and, for `both`, omit the parenthetical). Uncertain transliteration is withheld like a missing field.
6. **Directionality.** After a style produces the entry's runs, `emit_directional_runs` inserts FSI/PDI isolates around runs whose `script_of` disagrees with `profile.direction`, so mixed Latin/RTL content (URLs, DOIs, volumes) renders correctly in all three renderers.
7. **Per-language templates.** Front-matter/submission boilerplate looked up in `locale/templates/<lang>.py`; missing → English with a logged warning (a partial translation never blocks export).

### API endpoints
Extend `app/api/citation_schema.py`.
- `GET /locales` → `{"locales":[{"tag":"zh-Hans","label":"Chinese (Simplified)","direction":"ltr"},{"tag":"ar","label":"Arabic","direction":"rtl"}],"default":""}`
- `GET /citation-styles?locale=zh-Hans` → styles annotated/filtered by locale: `{"styles":[{"key":"gb7714-2015","edition":"GB/T 7714-2015","mechanism":"numbered","locale":"zh-Hans","recommended":true},{"key":"mla-9",...,"locale":null,"recommended":false}],"default":"mla-9"}` (`available_styles()` gains an optional `locale` filter; absent param = today's full list).
- `PATCH /projects/{id}/locale` `{"locale":"ar","name_script":"both"}` → `{"id":"…","locale":"ar","name_script":"both","citation_style":"mla-9","document_version":8}`. Mirrors how `create_project` writes `meta.citation_style`: validate against the registry, mutate `ThesisMeta`, re-dump to `project.meta`, bump `document_version` via `_commit_canonical`. Unknown locale → 422.

### Integration seams
- `app/renderers/styles/base.py` — `CitationStyle` Protocol gains the optional `locale` param.
- `app/renderers/styles/__init__.py` — register locale-specific styles in `_STYLES`; `available_styles()` gains a `locale` filter.
- `app/renderers/works_cited.py` — `_sort_key`/`sorted_entries` become collation-aware with a `LocaleProfile`; MLA delegates here so it inherits locale ordering.
- `app/renderers/md_renderer.py` + `docx_renderer.py` — pass `locale=resolve_locale(doc.meta.locale)` at the `sorted_entries` call sites; `docx_renderer._add_runs` sets the paragraph RTL flag from `profile.direction`; md/txt embed the isolate characters in `Run.text`.
- `app/canonical/model.py` — `ThesisMeta` gains `locale` + `name_script`.
- `app/api/citation_schema.py` — `/citation-styles` extended; new `/locales`. `app/api/projects.py` — new `PATCH /projects/{id}/locale`.

### External dependencies & fail-closed behavior
No ICU/unidecode is currently vendored. Add **PyICU** (correct locale collation + `Transliterator`, the accurate choice for CJK/Arabic) with **unidecode** as a lightweight last-resort romanizer. Both optional at import time behind a capability probe like `fonts.py` does for `soffice`. If PyICU is unavailable, `transliterate_name` returns `certain=False` and the renderer falls back to source script — degraded, never wrong. **Fonts:** the container (`Dockerfile.phase5`) bakes only Liberation + Times New Roman — **no CJK/Arabic coverage.** Add `fonts-noto-cjk` + `fonts-noto` and extend the `/readyz` font smoke to probe the required script fonts for the document's locale; missing → readiness warning, not a crash. **Bidi:** standard Unicode isolates (FSI/PDI) embedded in run text — LibreOffice/Word honor them natively; no runtime bidi library. **Fail-closed rule:** any uncertain romanization, missing collation, missing template, or missing font degrades to source script / English / a logged warning; bibliographic data and author identity are never fabricated.

### Test plan
- `tests/test_locale_ordering.py` — 陈 (Chen) and an Arabic author sort into correct collation position via ICU; falls back to `_sort_key` when locale `""`; English output byte-for-byte identical (golden).
- `tests/test_transliterate_names.py` — Han/Cyrillic/Arabic transliterate deterministically when ICU present; `certain=False` returns source script, never a guess; `name_script="both"` emits `source (translit)` only when certain.
- `tests/test_directionality.py` — `emit_directional_runs` wraps a Latin DOI inside an Arabic entry with FSI/PDI; LTR/`None` identity; `script_of` table.
- `tests/test_locale_punctuation.py` — CJK `、` + full-width; German `„…“`; French `«… »`; English unchanged.
- `tests/test_locale_render_docx.py`/`_md.py` — RTL sets docx paragraph RTL flag; md embeds isolates; both share `sorted_entries` output.
- `tests/test_citation_styles_endpoint.py` — `?locale=zh-Hans` marks `gb7714-2015` recommended; unfiltered returns all 14+; `/locales` lists direction; `PATCH /projects/{id}/locale` persists to `meta`, bumps `document_version`, 422 on unknown.
- `tests/test_fonts.py` (extend) — readiness probe reports missing CJK/Arabic fonts without raising.

### Effort, risk, dependencies
**L.** Registry/style/API plumbing is M and mirrors existing patterns, but correct typography, collation, and RTL detail across scripts is the long tail. **Risks:** typography minutiae (scope to a first tranche: de, fr, zh-Hans, ar, fa with golden tests); RTL/mixed-direction visual correctness depends on downstream renderers honoring isolates (verify LibreOffice PDF output, not just the run stream); the duplicate-column trap if a projection column is added. **Dependencies:** sequence **after 3.2 reference enrichment** — clean, authority-sourced multilingual metadata (original-script + romanized fields, script tags) is what makes transliteration and locale ordering reliable rather than best-effort; `ROADMAP.md` §4 places 3.7 at position 8 for exactly this reason.

---

## 3.8 The platform as a research instrument

### Overview
Acadensia already holds raw material almost no one else has: immutable `ManuscriptRevision` snapshots, `BlockOrigin`-tagged canonical blocks, and (once 3.1 lands) an append-only provenance ledger. This direction exposes that as a de-identified research corpus — but **strictly opt-in, deny-by-default, and gated behind the 3.1 provenance ledger plus the governance/entitlement surfaces.** No revision, block, or citation enters the corpus without an active, unrevoked, purpose-scoped research consent, and everything published is aggregated or k-anonymized before it leaves the boundary. Built wrong this is a liability; built fail-closed on the existing consent/pepper/entitlement primitives it is a trust feature.

### Data model & migrations
Three new tables (new `app/models/research.py`). The existing `consent_records` table (privacy-notice acceptance) is deliberately **not** reused — it models notice acceptance keyed to `privacy_notice_versions`, a different lifecycle.

**`research_consents`** — one row per (user, scope, terms version); revocation sets `revoked_at`, never deletes: `id`; `user_id` FK CASCADE indexed; `institution_id` FK SET NULL nullable; `scope` `String(40)` (`revision_history|citation_patterns|ai_provenance|all`); `terms_version` `String(20)`; `granted_at`; `revoked_at` nullable (NULL = active); `granted_by`/`revoked_by` FK SET NULL; `evidence` JSONB (UA/IP hashed via `_privacy_hash`, never raw). Index `(user_id, scope, revoked_at)`; **partial** unique `(user_id, scope) WHERE revoked_at IS NULL` (so a user cannot hold two live grants; a plain unique would wrongly block re-grant after revocation).

**`corpus_subjects`** — the pseudonym ledger, the only place a stable donor pseudonym ↔ real `user_id` link lives, kept out of every export: `id`; `user_id` FK CASCADE; `subject_pseudonym` `String(64)` UNIQUE (`research_pseudonym(user_id)` — HMAC over the pepper); `first_seen_at`.

**`corpus_records`** — append-only de-identified staging (one row per exported unit; DP/aggregation runs over it before publication): `id`; `corpus_run_id` FK CASCADE indexed; `scope` `String(40)`; `subject_ref` `String(64)` indexed (pseudonym, **never** `user_id`); `record_type` `String(40)` (`revision_delta|citation_pattern|provenance_rollup`); `source_revision_hash` `String(64)` (`opaque_identifier`-style hash of revision id+checksum; de-dupes without exposing identity); `payload` JSONB (already-anonymized, generalized fields only); `k_bucket` `String(120)` nullable indexed (quasi-identifier bucket for k-anonymity); `created_at`. Plus `corpus_runs`: `id`, `cadence`, `started_at`, `completed_at`, `terms_version`, `record_count`, `suppressed_count`, `dp_epsilon` Numeric(6,3) nullable, `state` (`building|published|withdrawn`).

**Migration** (`down_revision="0021"`), following `0020_usage_counters.py` shape (explicit `sa.Column`, named constraints). **Duplicate-column trap:** `consent_records` already has `withdrawn_at` and `entitlement_grants` already has `revoked_at` — do **not** reuse those tables or add a second consent column; create the distinct `research_consents.revoked_at` on a new table, keep the models in a separate module so autogenerate cannot target the wrong table. Create the partial unique index with explicit `postgresql_where=sa.text("revoked_at IS NULL")`. Bump `Settings.SCHEMA_VERSION`.

### Module layout
```
app/research/
  __init__.py
  consent.py       # grant/revoke/query research consent, fail-closed gate
  anonymize.py     # PII strip/hash/generalize; pseudonym derivation on the pepper
  corpus.py        # export pipeline: gather -> anonymize -> aggregate/DP -> stage
  governance.py    # research-terms versions, ethics-approval gate, DP thresholds (config)
app/models/research.py          # the tables above
app/api/research.py             # endpoints
migrations/versions/<next>_research_corpus.py
```
`governance.py` reads gates from `app/core/config.py` (defaults locked closed): `RESEARCH_CORPUS_ENABLED=False`, `RESEARCH_TERMS_VERSION=""`, `RESEARCH_ETHICS_APPROVAL_REF=""`, `RESEARCH_K_ANONYMITY=20`, `RESEARCH_DP_EPSILON=1.0`.

### Key interfaces & signatures
```python
# app/research/anonymize.py
def research_pseudonym(user_id: UUID, *, salt: str = "subject") -> str:
    """Stable, non-reversible donor id. HMAC-style over the privacy pepper so it
    cannot be recomputed without the secret, unlike bare opaque_identifier."""
    pepper = get_settings().effective_privacy_hash_pepper
    return hashlib.sha256(f"{pepper}\x00{salt}\x00{user_id}".encode()).hexdigest()
def revision_fingerprint(revision_id: UUID, checksum: str) -> str: ...
_PII_META_FIELDS = ("candidate", "college", "guide", "hod", "acknowledgement")
def anonymize_snapshot(snapshot: dict) -> dict:
    """Strip ThesisMeta.candidate/college/guide/hod, drop acknowledgement/
    certificate/declaration front-matter, replace run text with structural
    features (block count, origin, marker kinds, token-length bucket). Provenance/
    structure only — never raw author prose."""
def generalize(value: str, kind: Literal["month","degree","institution"]) -> str: ...

# app/research/consent.py
async def has_research_consent(db, user_id: UUID, scope: str) -> bool:
    """DENY BY DEFAULT. True only if a row exists with matching scope (or 'all'),
    revoked_at IS NULL, and terms_version == settings.RESEARCH_TERMS_VERSION
    (a superseded terms version = no consent)."""
async def grant_research_consent(db, *, user_id, scope, terms_version, granted_by, evidence) -> ResearchConsent: ...
async def revoke_research_consent(db, *, user_id, scope, revoked_by, reason=None) -> None: ...  # idempotent

# app/research/corpus.py
class CorpusRecord(BaseModel):        # published schema — no free text, no ids
    subject_ref: str
    scope: Literal["revision_history","citation_patterns","ai_provenance"]
    record_type: str
    source_revision_hash: str
    payload: dict
    k_bucket: str | None
async def k_anonymize(records, *, k) -> tuple[list, int]:
    """Suppress any record whose k_bucket has fewer than k members. Fail-closed:
    unknown bucket -> suppressed."""
def dp_count(true_count: int, *, epsilon: float) -> float: ...   # Laplace; falls back to suppression-only if no DP lib
async def build_corpus_run(db, *, cadence: str) -> CorpusRun: ...
```

### Core algorithm / flow
1. **Consent gating (deny-by-default, revocable).** Every gather query joins `research_consents` and filters `revoked_at IS NULL AND terms_version = current`. No row → the user's data is never selected. `has_research_consent` returns `False` on any ambiguity (missing scope, stale terms, ethics gate off).
2. **Governance preflight.** `build_corpus_run` refuses to start unless `RESEARCH_CORPUS_ENABLED`, a non-empty `RESEARCH_TERMS_VERSION`, and `RESEARCH_ETHICS_APPROVAL_REF` are all set → else `ResearchGovernanceError`, nothing produced.
3. **Gather.** Pull `ManuscriptRevision.canonical_snapshot` + 3.1 provenance events + citation data only for consented (user, scope) pairs.
4. **De-identification.** Per unit: (a) **strip** `ThesisMeta.candidate/college/guide/hod`, exact dates, acknowledgement/certificate/declaration/title_page front-matter; (b) **hash** `user_id`→`research_pseudonym`, `revision_id`→`revision_fingerprint`; (c) **generalize** run text → structural features (block/origin counts, marker kinds, edit-distance buckets between revisions, citation-style + source-type histograms), month→quarter, institution→tier. Output carries **no raw prose and no author identifier**.
5. **Aggregation / DP thresholds.** Stage `corpus_records`, then `k_anonymize(k=RESEARCH_K_ANONYMITY)` suppresses under-populated quasi-identifier buckets; aggregate stats released via `dp_count(epsilon=RESEARCH_DP_EPSILON)`. Suppressed counts recorded on the run for audit.
6. **Export cadence.** A scheduled job (reusing `app/services/job_queue.py`) runs weekly/monthly, marks the run `published`, writes an immutable manifest (terms version, ethics ref, epsilon, k, counts).
7. **Revocation propagation.** Revoking sets `revoked_at`; the **next** run's gather no longer selects that subject, so their contributions disappear from all future exports. Already-published aggregates are DP/k-protected (non-identifying by construction); an optional hard-withdrawal path deletes staged `corpus_records` by `subject_ref` immediately. Fail-closed throughout: any error in steps 1–5 aborts the run rather than emitting partial/raw data.

### API endpoints
- `POST /research/consent` `{"scope":"revision_history","terms_version":"2026-07"}` → 201 (409 if terms_version ≠ current, 403 if `RESEARCH_CORPUS_ENABLED` false).
- `DELETE /research/consent/{scope}` → 200 (idempotent).
- `GET /research/consent` → the caller's grants.
- `GET /research/shared` — "what is shared about me": runs `anonymize_snapshot` live, read-only → `{"subject_ref":"…","records":[{"record_type":"revision_delta","payload":{…}}]}`. Transparency surface; shows exactly what leaves, minus identity.
- `POST /research/corpus/runs` — admin only (governance capability + `require_recent_reauthentication`) `{"cadence":"monthly"}` → 202.
- `GET /research/corpus/runs/{run_id}` — admin: manifest + suppression stats.

### Integration seams
- **Pepper / hashing:** `app/core/config.py::effective_privacy_hash_pepper`, the `_privacy_hash` pattern in `app/commercial/sessions.py`, `opaque_identifier` in `app/commercial/observability.py`. `research_pseudonym` uses the pepper (not bare `opaque_identifier`) so pseudonyms are unforgeable.
- **Provenance ledger (3.1):** hard dependency — the append-only per-block event log is the `ai_provenance` scope's source. Until 3.1 ships, that scope stays disabled.
- **Revision history:** `app/models/manuscript_revision.py` (`canonical_snapshot`, `checksum`, `supersedes_revision_id` for deltas); read paths in `manuscript_service`/`export_service`.
- **Entitlements/guards:** gate `research.corpus.export`/`research.consent` through `EntitlementContext` + `require_entitlement` (`app/commercial/entitlements.py`); admin export deniable per-edition like `export.pdf` in `guards.py`.
- **Usage accounting:** corpus runs recorded via `record_usage`/`reserve_usage` and the `usage_counters` upsert pattern (migration 0020).

### External dependencies & fail-closed behavior
DP library optional (`python-dp`/`diffprivlib` behind a try-import); if absent, `dp_count` returns exact counts **only through the k-anonymity suppression gate**, never a raw count for small buckets. Ethics/governance gates all default empty/false; any one absent aborts export (mirrors the production `_validate` discipline in `config.py`). Absence of consent = exclusion: gather is an inner join on live consent — no code path reads an unconsented user's data. Revocation propagates on the next run; published aggregates remain non-identifying by k/DP construction.

### Test plan
- `tests/test_research_consent.py` — grant creates active row; duplicate live grant blocked by partial unique index; revoke idempotent; `has_research_consent` returns `False` for no-row / revoked / stale-terms (deny-by-default matrix).
- `tests/test_research_anonymize.py` — `anonymize_snapshot` output contains no value from `candidate/college/guide/hod`, no acknowledgement/declaration front-matter, no raw run text (assert against planted PII); `research_pseudonym` stable per user, differs across users, ≠ `opaque_identifier(user_id)`.
- `tests/test_research_corpus.py` — consented user appears; **revoke → absent from next run**; unconsented never appears; `k_anonymize` suppresses below-k buckets and counts; `dp_count` falls back to suppression-only when DP lib stubbed absent; governance preflight raises when any gate env empty.
- `tests/test_research_api.py` — consent CRUD + `/research/shared` on both mounts; `/research/shared` returns no identity fields; admin export 403 without capability, 202 with it.

### Effort, risk, dependencies
**L.** Four tables + one migration are small; the weight is the anonymization/DP pipeline, the transparency surface, and getting fail-closed right everywhere. **Risks (dominant = privacy/ethics/legal):** re-identification via quasi-identifiers (→ k-anonymity + generalization + DP), pepper compromise re-linking pseudonyms (→ keep the `corpus_subjects` map out of every export, treat the pepper as a top-tier secret), consent drift across terms versions (→ version-pinned `has_research_consent`), and the duplicate-column/wrong-table trap. Engineering risk low; policy/ethics risk high — ships only with a real ethics-review reference wired into the governance gate. **Hard dependencies:** the 3.1 provenance ledger (for `ai_provenance`) and the governance/entitlement work; both land first, matching the roadmap's "Later, gated behind provenance + governance."

---

## Consolidated sequencing

From `ROADMAP.md` §4, annotated with the LLD effort reads above:

**Now** — 3.2 Reference enrichment (M; retires `[VERIFY]`, unblocks 3.3/3.7), 3.1 AI provenance (M; model groundwork exists, unblocks 3.8), 3.3 verbatim quote verification (M; the alignment half is L/later).

**Next** — 3.4 Venue compliance (S–M for the pure validators, ship first; M/L camera-ready), 3.5 JATS export + LaTeX import (S–M/M; deposit adapters M–L, partner-gated), 3.6 Supervision workflow (M; do the authz composition carefully).

**Later** — 3.3 claim–citation alignment (L, research-grade), 3.7 Multilingual (L; after 3.2), 3.8 Research corpus (L; hard-gated behind 3.1 + governance).

Each lands in an existing seam and preserves the never-guess, canonical-first, governed-phase invariants. When implemented, migrations take consecutive revision ids in build order (see *Cross-cutting conventions*), each bumping `SCHEMA_VERSION`, each with a dedicated migration round-trip test — because the unit suite's `create_all` path will not catch a broken chain.
