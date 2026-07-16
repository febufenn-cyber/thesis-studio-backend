# Acadensia — Service Scope & Feature-Intention Audit

*This document exists so that no code in this repository is unexplained. Every
feature below states what it is FOR, where it lives, how we KNOW it works, and
where a human can touch it. Anything that cannot pass those four questions is
listed in §6 as a decision, not silently kept.*

---

## 1. The promise

**Acadensia is the integrity-first thesis studio.** A student writes their
dissertation in a workspace where every claim is traceable, every edit is
accountable, every quotation is checkable against its source, and the AI
assists without ever ghost-writing — then submits a sealed, verifiable package
their institution can trust.

The one-line test for any feature: *does it help a scholar produce work they
can defend?* If a feature cannot be traced to that promise, it does not belong.

## 2. Who it serves, and the job each one hires us for

| Role | The job they hire Acadensia for |
|---|---|
| **Student** | "Get me from blank page (or messy draft) to a submission my examiner can't tear apart on integrity grounds." |
| **Advisor / committee** | "Show me exactly what changed, let me comment and approve at the right granularity, prove what I reviewed." |
| **Department / institution** | "Govern format and policy without reading private drafts; get sealed, attested submissions; own the audit trail." |
| **Operator (format office)** | "Apply institutional formatting rules without touching academic content." |

## 3. The non-negotiable law of the codebase

**Never guess.** Advisory features never set `verified`. Resolved/scored ≠
verified. Missing information becomes a loud `[VERIFY]` marker, never a
fabricated value. Review exports render honest "[UNVERIFIED]" banners; final
exports hard-refuse incomplete citations. A fabrication is treated as ten
times worse than a miss. Every deterministic rule in the extraction pipeline
exists to pass a **named case in a frozen, append-only eval corpus** —
`tests/citation_corpus.py` (37 entries, 152 fields, 100% required) and
`tests/quote_corpus.py` (recall ≥ 0.80 gate, zero fabrications) — so no rule
is unexplained noise: delete one and a named test tells you which scholarly
situation just broke.

## 4. The six pillars — feature → intent → proof → UI

### P1 · Ingest & canonical truth
*One source of truth: the canonical ThesisDocument. Uploads are immutable.*

| Feature | Code | Proof | UI |
|---|---|---|---|
| DOCX upload, immutable revisions, SHA-256 | `manuscripts.py`, `manuscript_service` | phase tests; Priya E2E | Studio → Upload DOCX |
| Package safety preflight + malware scan | `ingest/preflight`, `malware_service` | unit tests | automatic on upload |
| Structure detection (chapters, headings, front matter) | `ingest/structure` (PARSER_VERSION 2.1) | parser fixtures incl. heading-recovery cases | Structure tree |
| Citation extraction & deterministic resolution | `ingest/citations` | **frozen corpus, 152/152 fields** | Sources tab |
| Inline quotation extraction | `verification/inline_quotes` | **quote corpus, 0 fabrications** | Integrity → quotes |
| Canonical model + in-app JSONB migrations | `canonical/model`, `canonical/migrations` | schema-version tests (0029) | (substrate) |

### P2 · The integrity engine
*The reason to choose Acadensia over a word processor.*

| Feature | Code | Proof | UI |
|---|---|---|---|
| Verbatim quote verification vs source text | `verification/quotes`, `quote_verification*` | LLD 3.3 tests | Library → quote rows; paste-to-verify |
| Open-access auto-verify (E4) | `references/fulltext` | E4 tests | AutoVerify button |
| Claim–citation alignment (MF2) | `verification/alignment` | MF2 tests | Integrity review items |
| Integrity Report — provenance, **not** detection | `integrity.py`, `integrity_report` | MF4 tests | Integrity tab |
| AI Use Statement + provenance timeline | `provenance.py`, `provenance_service`, `ai/disclosure` | tests; in Submission Pack | Integrity tab |
| Citation authority resolution ([VERIFY] → resolved) | `references_resolve`, `references/service`, `reconcile`, `cache` | resolve tests | Sources → Resolve |
| Retraction check (Crossref) | `references/retraction` | E-tests | Source intelligence |
| Source & journal trust signals (E1) | `references/trust`, `source_trust.py` | E1 tests | Library → per-source |
| Ambiguous-citation human resolution | `resolutions.py` | tests | Integrity review |

### P3 · Writing & scholarship
*Assist, never ghost-write.*

| Feature | Code | Proof | UI |
|---|---|---|---|
| Structured block editor, undo/redo, checkpoints, search | `editor.py`, `editor_service` | Phase 2 tests | Editor |
| Robofox Scholar: 9 grounded task modes, proposal-only mutations, human accept/reject | `ai/*` (orchestrator, context, proposal_engine, safety) | Phase 3 tests + deterministic eval harness | Robofox tab |
| **Per-domain discipline voice** (9 voices) | `ai/domain_guidance` | precedence + totality tests | follows Readiness profile |
| Prompt-injection defense (untrusted-content wrapping) | `ai/safety` | unit tests | (substrate) |
| Start-from-zero guide (5 playbooks, scaffolds) | `guide.py`, `guide/playbooks` | scaffold tests incl. id-persistence regression | Fox orb, everywhere |
| Literature discovery (MF1) | `references_search` | MF1 tests | Sources → Search |
| Research copilot insight (E3) | `references/copilot`, `copilot.py` | E3 tests | Library → insight |
| Writing quality, advisory only (E7) | `writing.py` | E7 tests | Writing tab |
| Bibliography in 10,000+ CSL styles (E5) | `references/csl_render`, `csl_styles`, `bibliography.py` | E5 tests | Bibliography tab |
| Reference import: BibTeX/RIS/CSL/Zotero | `references_import`, `renderers/bibtex_import`, `ris` | import tests | Import tab |

### P4 · Output & submission
*The artifact is the product.*

| Feature | Code | Proof | UI |
|---|---|---|---|
| DOCX renderer (FORMAT_SPEC §1–7; strict/review honesty modes) | `renderers/docx_renderer`, `works_cited` | format tests; honest-fallback tests | Export |
| PDF / Markdown / Text renderers | `pdf_renderer`, `md_renderer`, `txt_renderer` | render tests | Export |
| LaTeX / JATS / CSL interchange (3.5, E6) | `renderers/latex`, `jats`, `interchange.py`, `interop_pandoc` | interchange tests | Export → interchange |
| Authoritative PDF previews | `previews.py`, `preview_service` | preview tests | Preview tab |
| **Submission Pack — one click, one zip** (thesis + integrity report + AI statement + quote verification + provenance + manifest w/ checksums) | `submission_pack.py` + service | pack tests; Priya E2E verifies checksums | Export → Submission Pack |
| Sealed institutional submissions, attestations, external review | `submissions.py`, `collaboration/sealing`, `sealed_guard`, `external_downloads` | Phase 4 tests | Reviews / institution flow |
| Zenodo DOI deposit + ORCID (MF3) | `deposits.py`, `deposit_service` | MF3 tests | Deposit & DOI tab |
| Data portability (project + account) | `data_portability.py` | tests | API keys & security |
| Format profiles + locales (3.7) | `renderers/profiles`, `locales.py` | profile tests | Settings |
| Domain profiles + submission readiness (8 disciplines) | `domains/profiles`, `domain_profiles.py` | profile tests | Integrity → Readiness |

### P5 · Governance & collaboration
*Every role has authority; no role has all of it.*

| Feature | Code | Proof | UI |
|---|---|---|---|
| Committee roles, deny-by-default permissions | `collaboration/committee` | permission-table tests | Supervision tab |
| Review cycles on immutable snapshots; anchored comments; human suggestions | `collaboration/workflow` | Phase 4 tests | Reviews tab |
| Block-anchored feedback (3.6) | `collaboration/block_feedback`, `supervision.py` | 3.6 tests | Supervision → comments |
| Approval invalidation on content change | `approval_invalidation`, `editor_hooks` | invalidation tests | automatic |
| Semantic (meaning-level) diff | `collaboration/semantic_diff` | diff tests | Supervision → compare |
| Institutional policies/profiles/templates, versioned + staged | `institutional.py`, `institutional_lifecycle`, `collaboration/governance` | governance tests | Institution console (read); API-first mutations |
| Presence (no live cursors by design) | `presence.py` | tests | topbar dots |
| Notifications without prose leakage | `collaboration/notifications` | tests | Notifications |
| Audit timeline, privacy-aware | `collaboration/audit` | tests | History |
| Supervisor's desk | SPA `/supervise` | screenshot-verified | sidebar |

### P6 · Platform & trust substrate
*What a college must be able to ask about before adopting.*

| Feature | Code | Proof | UI |
|---|---|---|---|
| OTP auth (+ optional Google, config-gated), revocable sessions | `auth.py`, `google_auth` | auth tests | Sign-in |
| Device-visible sessions + step-up reauth | `commercial_sessions` | tests | API keys & security |
| Scoped API keys, fail-closed matrix | `api_keys.py`, `deps.py` | scope-matrix tests | API keys |
| Rate limiting (fixed slowapi 500 bug), security headers, CORS | `core/rate_limit`, middleware | regression test | (substrate) |
| Durable Postgres job queue + workers | `job_queue` | worker tests; Priya E2E | job status |
| Storage (R2 / local), retention sweeps | `storage_service`, `retention_scheduler` | retention tests | Settings/policy |
| Privacy lifecycle (export/delete, consent, notices) | `commercial_privacy` | tests | API keys & security |
| Billing/entitlements/usage; ops/incidents; SLOs; release identity | `commercial_billing`, `_operations`, `_reliability` | tests | Institution console (read-only); rest deliberately API-first |
| Observability: request logging, trace ids, readiness probes | `main.py`, `readiness_service` | probe tests | build badge |

## 5. Deterministic rules are not noise — here is the discipline

Every regex/heuristic in `ingest/citations.py` and `verification/*` maps to a
**named corpus case** (e.g. `trailing-initial author split` exists because of
corpus entries like *"Desai, K. The Inheritance of Loss…"*; the
`year-in-head fragment guard` exists because a real MCC works-cited page broke
without it). The corpora are **append-only**: rules can only be added with a
case proving why, and can never silently regress (pytest gates: citation
fields 100%, quote recall ≥ 0.80, fabrications = 0). This is the opposite of
slop: it is the only part of the codebase where every line has a *machine-
checked* reason to exist.

## 6. The honest findings — decisions needed (the only real noise risk)

One legacy layer predates the studio and is still mounted:

| Item | What it is | Recommendation |
|---|---|---|
| `/legacy` route + `index.html` + `phase1*.js/css` | The original chat-first console | **Retire**: remove route + assets after one release with a redirect notice |
| `chat.py`, `sessions.py`, `claude_service`, `compile_service` | v1 "chat with Claude → compile thesis from messages" pipeline | **Retire or quarantine behind `LEGACY_CHAT_ENABLED=false` default** — it bypasses the proposal-engine governance that makes Robofox trustworthy |
| `active_registry.py` | Read endpoints only the phase-1 console uses | Retire with the console |
| `POST /auth/request-link` (magic link) | Alternative auth, needs mail infra | Keep config-gated or remove; decide with deployment plan |
| `ai_partner: link-legacy` | One-time migration shim | Remove after legacy retirement |

Nothing else in the repository failed the four questions (intent, code,
proof, surface). The `commercial_*` modules are **enterprise-ahead by
design** — a college procurement checklist (sessions, privacy, SLOs, billing,
incidents) — surfaced read-only in the Institution console, mutations
deliberately API-first as runbook operations.

## 7. The guardrail going forward

A change may not merge unless it can fill in this row:

> **Feature → intent (which pillar / which promise) → proof (test or corpus
> case) → surface (UI location, or "API-first because …")**

This file is that ledger. Update it in the same commit as the feature.
