# Acadensia Domain Expansion — Research & Architecture Brief

**Status:** design proposal (planning artifact, not yet implemented)
**Scope:** generalize Acadensia from a hardcoded *MA-English / University of Madras / MLA-9* tool into a domain-agnostic, research-grade academic authoring and integrity platform spanning humanities, social science, all engineering, STEM, health, arts & design, law — up to PhD theses and peer-reviewed papers an AI researcher would publish from.

The thesis of this brief: Acadensia's real moat is **not** the MLA formatter. It is the *governed integrity pipeline* — deterministic parse → registry of verified sources/quotes → verifier-gated export → inert, human-approved, per-passage-attributed AI. That machinery is discipline-neutral. What is currently hardcoded is only the **surface**: one citation style (MLA-9), one document structure (MCC/UoM MA dissertation), and one institution profile. Generalizing three well-bounded surfaces unlocks every domain without touching the moat.

---

## Part 1 — The citation-standard data map (the "MLA, likewise for engineering and every domain" ask)

Each domain has a *dominant* style plus common alternates. The data Acadensia must model per style is: **edition** (styles revise, and a thesis must target one), **mechanism** (author–date vs numbered vs notes), **in-text form**, **reference-list ordering**, and the **required metadata fields** (which differ sharply — a chemistry citation needs a DOI and CASRN context; a legal citation needs a reporter and pincite; an engineering citation needs a standard number).

Current editions verified against library and publisher sources (see Sources); editions change, so each is a versioned value in the model, never a constant.

| Domain / field | Dominant style | Current edition | Mechanism | Reference ordering |
|---|---|---|---|---|
| English, literature, languages | **MLA** | 9th (2021) | Author–page, Works Cited | Alphabetical by author |
| History, some philosophy/art history | **Chicago** (Notes–Bibliography) | 17th (2017); 18th (2024) rolling out | Footnotes + Bibliography | Alphabetical |
| Psychology, education, sociology, comms | **APA** | 7th (2020) | Author–date | Alphabetical |
| Business, economics | APA or Chicago (Author–Date) | — | Author–date | Alphabetical |
| Electrical/electronic, general engineering | **IEEE** | 2021 reference guide | Numbered [1] | Order of appearance |
| Mechanical engineering | **ASME** | current journal guide | Numbered [1] | Order of appearance |
| Civil engineering | **ASCE** | current author–date guide | Author–date | Alphabetical |
| Computer science, AI/ML | **ACM** (also IEEE) | ACM 2020+ (numeric & author–date variants) | Numbered or author–date | By appearance / alphabetical |
| Chemistry | **ACS** | ACS Guide to Scholarly Communication (2020) | Numbered (superscript) or author–date | By appearance |
| Physics, astronomy | **AIP** / IEEE | AIP current | Numbered | By appearance |
| Biology, life sciences | **CSE** (Council of Science Editors) or Vancouver | CSE 8th (2014) | Name–Year, Citation–Sequence, or Citation–Name | Varies by CSE system |
| Medicine, nursing, public health | **Vancouver / ICMJE** | ICMJE current | Numbered | By appearance |
| Medicine (AMA-house) | **AMA** | 11th (2020) | Numbered (superscript) | By appearance |
| Mathematics | **AMS** (amsrefs/BibTeX) | current | Author–year or numbered | Alphabetical |
| Law (US) | **Bluebook** | 21st (2020) | Footnote citations | N/A (notes) |
| Law (UK/Commonwealth) | **OSCOLA** | 4th | Footnotes | N/A |
| Arts, design, architecture | Chicago or MLA (+ image/exhibition citation) | — | Notes or author–page | Alphabetical |

Three structural families cover almost all of the above, and this is what the code should model rather than 20 special cases:

1. **Author–date** (APA, ASCE, Chicago Author–Date, CSE Name–Year, Harvard): in-text `(Author, Year)`, alphabetical list. One renderer family, parameterized.
2. **Numbered / citation-sequence** (IEEE, ACM-numeric, ACS, AMA, Vancouver, AIP, CSE Citation–Sequence): in-text `[n]` or superscript, list ordered by first appearance. One renderer family.
3. **Notes–bibliography** (Chicago NB, Bluebook, OSCOLA): footnote/endnote citations plus a bibliography; needs a note-numbering + ibid./short-form engine. A distinct renderer family.

MLA-9 is a special-cased **author–page** variant of family 1. So Acadensia already has one member of family 1 implemented (`works_cited.py`); the generalization is to (a) lift the shared author–date machinery out, (b) add the numbered family, and (c) add the notes family later.

**Per-style required metadata** (why the registry must be field-flexible, not MLA-shaped):

- IEEE/ACM/engineering: often cite **standards** (`IEEE 802.11`, ISO), **patents**, **datasets**, **technical reports** — fields the current MLA-only `Source` model has no slot for.
- ACS / medicine: **DOI is mandatory**, PubMed ID (PMID), article numbers, no article titles in some ACS variants.
- CS/AI: **arXiv ID**, DOI, conference vs journal distinction, **BibTeX entry type** (`@inproceedings`, `@article`, `@misc`), venue + year.
- Law: reporter, volume, court, pincite, year — an entirely different citation grammar (notes engine).
- Data/software citation (Force11 / CodeMeta): DOI, version, repository, RRID — increasingly required by journals and exactly what an AI researcher needs to cite a model or dataset.

Implication: the registry's `Source.fields` must become a **style-and-type-aware schema** (validated per `source_type × style`), not the fixed MLA field set it is today.

---

## Part 2 — Document-structure profiles (PhD, engineering project, paper, portfolio)

Citation style is orthogonal to document structure. Acadensia currently bakes one structure (MA dissertation: title page → certificate → declaration → acknowledgement → contents → chapters → works cited). Each credential/output has its own required skeleton, and this is the *second* hardcoded surface to generalize into a **DomainProfile**.

- **MA / MPhil dissertation** (current): front matter + chapters + works cited. Keep as one profile.
- **PhD thesis**: adds abstract (often multilingual), list of publications, extended literature review, methodology chapter, contribution statement, appendices, and a **declaration of AI use** (now mandated by many universities — Acadensia's provenance layer is a *native* advantage here). Often allows a **thesis-by-publication** structure (stapled papers + linking commentary).
- **Engineering project / capstone report**: abstract → problem statement → requirements → design → implementation → testing/results → discussion → conclusion → references → appendices (code, schematics, BOM). Numbered citations, heavy figures/tables/equations.
- **Journal article**: Title → Abstract → Keywords → IMRaD (Introduction, Methods, Results, and Discussion) → References. This is the near-universal science paper skeleton.
- **Conference paper (CS/AI)**: venue LaTeX template (NeurIPS/ICML/CVPR/ACL/IEEE), 8-page limit, abstract, IMRaD-ish, references, appendix, reproducibility checklist, ethics/broader-impact statement.
- **Lab report / CSE**: IMRaD subset.
- **Design / arts studio**: portfolio + reflective commentary + image plates with caption/credit citation; assessment against a rubric rather than a verifier of quotations — needs a different "verifier" notion (see Part 5).
- **Law**: issue → rule → application → conclusion (IRAC), footnote-cited.

Structurally these reduce to a small set of **section-graph templates** with required/optional/repeatable nodes, front/back matter, and a numbering policy — a natural generalization of the existing `FrontMatterEntry` + `ChapterDoc` model.

---

## Part 3 — Why an AI researcher would choose Acadensia

The request said the bar is "even an AI researcher should love to work with Acadensia, do their research and publish." Concretely, that means meeting the CS/AI publishing workflow where it lives and making integrity a feature, not friction:

1. **LaTeX + BibTeX as first-class I/O.** Ingest a `.bib` file into the source registry (map BibTeX entry types → source types → fields); export references in BibTeX and in the venue's `.bst` style. Round-trip with Overleaf-style `.tex`. Without this, no ML researcher will switch.
2. **Venue templates as DomainProfiles.** NeurIPS/ICML/CVPR/ACL/IEEE/ACM conference skeletons with page/format constraints, plus the **reproducibility checklist** and **broader-impact/ethics statement** these venues now require — Acadensia can *enforce* their presence before "export," which is exactly its verifier pattern applied to submission-readiness.
3. **Provenance as a publishing asset.** Journals and conferences increasingly require an **AI-use disclosure**. Acadensia already tracks, per passage, whether text is `manuscript_import | human | ai_proposal` (implemented in the provenance commit on this branch) and aggregates an AI-disclosure statement. That turns a compliance headache into a one-click, defensible artifact — a genuine reason to author *in* Acadensia rather than paste into it.
4. **Data & model citation.** First-class Force11 dataset/software citation (DOI, version, RRID, repo) so a paper can correctly cite the datasets and models it uses — table-stakes for reproducible ML.
5. **Grounded, inert AI that cannot fabricate citations.** The single biggest AI-authoring risk in research is hallucinated references. Acadensia's registry rule — *AI may only insert a direct quotation via a human-verified `quote_id`, and long quoted strings are rejected at three layers* — is precisely the guardrail a careful researcher wants. This is the differentiator versus a generic "write my paper" LLM.

The pitch to a researcher is therefore not "AI writes your paper" but "**an integrity-preserving authoring environment where AI assistance is grounded, attributed, and disclosure-ready, with native LaTeX/BibTeX and your venue's template.**"

---

## Part 4 — Architecture: three pluggable surfaces, one untouched core

The generalization is deliberately confined to three seams. The canonical model, command engine, verifier discipline, registries, and AI governance stay as-is.

**Seam 1 — `CitationStyle` interface (replaces the hardcoded `works_cited.py`).**
Define an abstract style with three implementations by family:

```
CitationStyle (protocol)
  key: str                      # "mla-9", "ieee-2021", "apa-7", "acs-2020", ...
  edition: str
  mechanism: Literal["author_page","author_date","numbered","notes"]
  required_fields(source_type) -> tuple[str, ...]
  format_reference(source, ordinal) -> RichText
  format_in_text(citation_ref) -> str      # (Author 12) | [3] | superscript | note
  sort_key(source) -> tuple | None         # None => order-of-appearance
```

`works_cited.py`'s MLA-9 logic becomes `styles/mla.py` (first impl). `styles/ieee.py` (numbered) is the proof that the abstraction holds across families. A registry maps `style_key -> CitationStyle`. Renderers call the style, not MLA functions. The existing `MissingCitationField` "never guess" discipline is preserved by making `required_fields` per style/type and letting the verifier flag gaps exactly as it does now.

**Seam 2 — `DomainProfile` (generalizes `renderers/profiles.py` + the MA structure).**
A profile binds: a **section-graph template** (Part 2), a **default citation style** (overridable), a **numbering policy** (roman front matter, arabic body, figure/table/equation numbering), and **submission-readiness rules** (which sections/artifacts must exist before export — e.g., reproducibility checklist for NeurIPS, declaration of AI use for a PhD). This is the natural home for "MA dissertation", "PhD thesis", "IEEE conference paper", etc. The current MCC/UoM profile becomes one `DomainProfile` instance; nothing about it regresses.

**Seam 3 — style-and-type-aware registry schema.**
`Source` gains a `source_type` (`article | book | chapter | conference_paper | standard | patent | dataset | software | webpage | thesis | report | legal_case | ...`) and its `fields` are validated against `required_fields(source_type)` of the target style. Add importers/exporters: **BibTeX** and **RIS** in, **BibTeX** and formatted references out. This is additive to the model (new nullable columns + a JSON field schema), so it is a clean migration.

**What does NOT change:** `app/canonical/model.py` block tree, `app/editor/` command engine, `app/ingest/verifier.py` integrity gate (it becomes style-parameterized but keeps its rules), the AI orchestrator/proposal governance, and per-user isolation. The moat is untouched; only the surfaces flex.

For **design/arts**, where "verification of quotations" is less central, the verifier generalizes to a **submission-readiness evaluator**: same fail-closed pattern, different rules (image credits present, rubric criteria addressed, portfolio plates captioned) rather than quote/source cross-checks.

---

## Part 5 — Indic / regional advantage carried forward

The existing Tamil/Indic direction is not lost in going multi-domain — it compounds. A **PhD thesis in Tamil literature**, an **engineering project report from an Indian institution**, or **regional-language STEM abstracts** all become DomainProfiles + style bindings on the same core, with Sarvam/Bhashini handling Indic voice/translation. "Domain-agnostic *and* Indic-native" is a combination no US-centric tool offers, and it maps directly onto the Madurai/AI4Bharat positioning.

---

## Part 6 — Phased rollout (non-breaking, test-gated)

1. **Foundation (this branch):** introduce `CitationStyle` protocol, refactor MLA-9 behind it (behavior-identical, existing tests stay green), add `IEEE-2021` as the second family, add `source_type` to the registry (nullable, defaulted). Migration + tests. *This is the piece being scaffolded now.*
2. **Structure:** add `DomainProfile` with 3 initial profiles — MA dissertation (existing), PhD thesis, IEEE/engineering project report. Section-graph templating over the existing front-matter/chapter model.
3. **Researcher I/O:** BibTeX/RIS import + BibTeX/formatted export; one venue template (e.g. IEEE conference) end-to-end.
4. **Breadth:** APA-7, ACS, Vancouver/AMA, Chicago NB (notes engine), CSE; more DomainProfiles; data/software citation.
5. **AI-researcher polish:** LaTeX round-trip, venue reproducibility/ethics enforcement, AI-use disclosure export, arXiv packaging.

Each phase is additive and gated by the CI-equivalent suite + migration round-trips already standing up in this session.

---

## Sources

- [Current APA, MLA & Chicago editions in 2026 — ReferenceChecker](https://referencechecker.org/blog/current-citation-styles-2026)
- [Citation Style Guide by Academic Discipline — GenText](https://gentext.ai/guides/en/citation-style-guide-by-discipline/)
- [Citation Styles for Engineers (IEEE / ASME / ASCE) — Texas Tech University Libraries](https://guides.library.ttu.edu/engineeringcitations)
- [ACS Style (2025) — University of South Carolina Libraries](https://guides.library.sc.edu/sciencecitationstyles/acs)
- [AMA 11th edition guide](https://www.readwonders.com/guides/citations/ama) · [Vancouver/ICMJE guide](https://www.readwonders.com/guides/citations/vancouver)
- [Reference Styles for ACM Papers](https://ht.acm.org/ht2024/reference-styles-for-acm-papers/) · [ACM reference formatting](https://www.acm.org/publications/authors/reference-formatting)
- [LaTeX templates for NeurIPS/ICML/CVPR/ACL — Underleaf](https://www.underleaf.ai/templates)
- [Citation Styles overview — University of Pittsburgh Libraries](https://pitt.libguides.com/citationhelp)
