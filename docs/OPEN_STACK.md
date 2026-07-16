# Open & free stack — what powers Acadensia

Every external capability in Acadensia runs on **open-source software or free
scholarly open-data APIs**. There are no paid data dependencies: the only keys
the platform ever needs are free-tier or optional-politeness keys. This is both
an engineering fact and a selling point — the integrity story is built on open
infrastructure the academic community already trusts.

This catalog is generated from the actual codebase (imports, HTTP hosts, invoked
binaries), not a wishlist. Each entry notes what it does, its licence/cost
posture, and the config gate that gates it.

---

## 1. Scholarly open-data APIs (all free; keyless unless noted)

These power reference resolution, enrichment, trust, identity and full-text.
All are network-gated (off in tests) and fail-closed — an outage yields
"unknown/unverifiable", never a fabricated result — and now sit behind a shared
retry/backoff + circuit-breaker transport so a provider outage can't hammer the
free endpoints.

| Service | Host | What it gives users | Cost / key |
|---|---|---|---|
| **Crossref** | api.crossref.org | DOI metadata, retraction notices, the "polite pool" | Free, keyless (optional `CROSSREF_MAILTO`) |
| **OpenAlex** | api.openalex.org | Works/venue metadata, open-access status, journal signals (h-index, DOAJ, citations) for source trust | Free, keyless |
| **arXiv** | export.arxiv.org | Preprint metadata resolution | Free, keyless |
| **OpenLibrary** | openlibrary.org | Book metadata resolution | Free, keyless |
| **DOI.org** | doi.org | Canonical DOI resolution | Free, keyless |
| **ORCID (public)** | pub.orcid.org | Verified researcher-identity lookup | Free, keyless (public API) |
| **ROR** | api.ror.org | Research Organization Registry — canonical institution IDs | Free, keyless |
| **Semantic Scholar** | api.semanticscholar.org | Paper insight: TLDR, citation counts, related work (research copilot) | Free (optional key for higher limits) |
| **Europe PMC** | ebi.ac.uk/europepmc | Open-access full text feeding quote verification | Free, keyless |
| **Unpaywall** | api.unpaywall.org | Best open-access link for a DOI | Free (needs a free email) |
| **Sherpa Romeo** | v2.sherpa.ac.uk | Journal self-archiving / open-access policy | Free key (optional) |
| **CSL styles repo** | raw.githubusercontent.com/citation-style-language | 10,000+ citation styles fetched on demand | Free, open (CC-BY-SA) |
| **Zotero** | api.zotero.org | Import a user's Zotero library into the registry | Free (user's own key, used once, never stored) |
| **Zenodo** | zenodo.org / sandbox | Deposit a finished export for a DOI | Free (user/instance token; sandbox by default) |

Related open standards also consumed: **DOAJ** signals (via OpenAlex
`is_in_doaj`) and **OpenCitations**-style citation graphs (via the above).

## 2. Open-source engines & libraries (the processing core)

| Component | Licence | Role |
|---|---|---|
| **FastAPI / Starlette / Uvicorn** | MIT/BSD | Async web framework + ASGI server |
| **SQLAlchemy + asyncpg + Alembic** | MIT | Async ORM, Postgres driver, migrations |
| **PostgreSQL** | PostgreSQL licence | Primary datastore + durable job queue |
| **Pydantic / pydantic-settings** | MIT | Validation, typed settings |
| **citeproc-py** | BSD | The CSL rendering engine — bibliographies in any of 10,000+ styles |
| **lxml / defusedxml** | BSD / PSF | XML parsing, hardened against XXE/entity attacks on uploads |
| **python-docx** | MIT | DOCX ingestion (manuscript upload) |
| **Pandoc** | GPL | Universal document interop (odt/docx/rst/epub/JATS/LaTeX…) |
| **LibreOffice (soffice)** | MPL | Authoritative PDF rendering pipeline |
| **PyJWT / cryptography** | MIT/Apache | Tokens, hashing, signing |
| **slowapi / limits** | MIT | Application-layer rate limiting |
| **httpx** | BSD | Async HTTP client for all outbound calls |
| **Pillow** | MIT-CMU | Image handling |
| **boto3** | Apache-2.0 | S3-compatible object storage (Cloudflare R2) |
| **pytest / ruff / mypy** | MIT | Test, lint, type-check |

## 3. Open tools the platform is designed to sit alongside

Referenced in the interop/verification design and reachable through the
integrations, all free/open: **GROBID** (PDF→structured references),
**anystyle** (citation parsing), **LanguageTool** (self-hostable grammar/style —
the E7 writing checker; point `LANGUAGETOOL_URL` at your own instance so text
never leaves the deployment), **Pandoc** and **citeproc** (above), and the
**CSL** ecosystem shared with Zotero/Mendeley.

## 4. Optional / non-core third parties (clearly separable)

Not required for the core academic workflow; each is gated and swappable:
**Anthropic** (the AI partner — the one genuinely paid dependency, and only for
the optional Robofox Scholar assistant); **Resend** (transactional email — any
SMTP/provider can replace it); **Google Identity** (optional social sign-in);
**Cloudflare R2** (S3-compatible storage — any S3 backend works); **ClamAV**
(open-source malware scanning on uploads).

---

## Why this matters (the pitch)

- **No paid data moat to rent.** Citation, identity, trust, full-text and
  formatting all run on open scholarly infrastructure — the same sources
  librarians and publishers trust — so per-user data cost is ~zero.
- **Self-hostable where privacy matters.** LanguageTool, LibreOffice, Pandoc,
  ClamAV and Postgres all run inside your own deployment; manuscript text need
  never touch a third party.
- **Honest provenance.** Because every enrichment is a named open source with a
  URL, the integrity report can cite exactly where each fact came from — which
  is the whole product.

*The single paid dependency is the optional AI assistant (Anthropic). Everything
that makes a thesis submission-ready — parsing, references, trust, verification,
bibliography, export, deposit — runs on free and open software.*
