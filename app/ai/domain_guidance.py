"""Per-domain guidance for Robofox Scholar's system prompt.

The task registry says WHAT Robofox is doing (diagnose, challenge, plan…);
this module says HOW scholars in the project's discipline argue, cite and
structure evidence, so the same task reads differently for a literature MA
dissertation than for an engineering project report.

Selection is deliberately layered and total:

1. ``project.meta["guide_playbook"]`` — set when the student scaffolded from
   zero with the Robofox guide (strongest signal of intent);
2. ``project.meta["domain_profile"]`` — an explicitly declared profile key;
3. ``project.doc_type`` — the coarse document type chosen at creation;
4. ``generic`` — always resolves; an unknown value never breaks a run.

Guidance is ADVISORY VOICE ONLY. It never overrides the safety policy, never
loosens verification rules, and never authorises silent style conversion
(safety rule: preserve the manuscript's own conventions).
"""

from __future__ import annotations

from typing import Any

GENERIC_KEY = "generic"

DOMAIN_GUIDANCE: dict[str, str] = {
    "ma_dissertation": (
        "DISCIPLINE: literature / humanities dissertation (MLA culture).\n"
        "- Argument = claim about a text, supported by CLOSE READING: quoted "
        "passages with page numbers, then analysis of HOW the language works.\n"
        "- Press for one named critical lens used consistently; flag lens-"
        "switching between chapters as coherence drift.\n"
        "- Evidence hierarchy: primary text first, then peer-reviewed "
        "criticism; treat plot summary presented as analysis as a weakness.\n"
        "- Citation culture: parenthetical author-page, Works Cited; quotes "
        "over four lines are block quotes.\n"
        "- In challenge/viva modes, ask what a skeptical examiner asks: why "
        "this text, why this lens, which critic disagrees, what would "
        "falsify the reading."
    ),
    "phd_thesis": (
        "DISCIPLINE: doctoral thesis (any field; monograph scale).\n"
        "- The unit of assessment is an ORIGINAL CONTRIBUTION; every chapter "
        "must state what it adds beyond the literature it reviews.\n"
        "- Press for an explicit contributions statement, a defended "
        "methodology chapter, and limitations acknowledged before examiners "
        "find them.\n"
        "- Literature review must be a mapped conversation (schools, gaps), "
        "not an annotated list; flag uncited claims of novelty.\n"
        "- In challenge/viva modes, simulate the external examiner: scope "
        "creep, unclaimed contributions, results that do not support the "
        "abstract's promises."
    ),
    "engineering_project_report": (
        "DISCIPLINE: engineering project report (IEEE culture).\n"
        "- Argument = requirements → design decisions → implementation → "
        "MEASURED evaluation. Every design choice needs a stated alternative "
        "and a reason it lost.\n"
        "- Numbers rule: flag any performance, cost or capacity claim with "
        "no unit, no baseline or no measurement method.\n"
        "- Citation culture: numeric [n] references (IEEE); figures and "
        "tables must be referenced from the prose and carry captions.\n"
        "- Methodology must be reproducible: versions, parameters, test "
        "conditions, datasets.\n"
        "- In challenge modes, press on: untested edge cases, safety and "
        "failure modes, why the baseline comparison is fair, what breaks at "
        "10x scale."
    ),
    "ieee_conference_paper": (
        "DISCIPLINE: IEEE conference paper.\n"
        "- Page-budget writing: every paragraph earns its space; abstract "
        "states problem, approach, headline result with numbers.\n"
        "- Contributions listed explicitly (usually 3); each must be "
        "defended in the body and revisited in the conclusion.\n"
        "- Citation culture: numeric [n]; related work positions the paper "
        "against named systems, not vague 'prior approaches'.\n"
        "- In diagnose mode, flag: results not tied to a table/figure, "
        "missing experimental setup details, conclusions stronger than the "
        "evidence section supports."
    ),
    "imrad_journal_article": (
        "DISCIPLINE: IMRaD journal article (sciences; APA/Vancouver "
        "cultures).\n"
        "- Structure discipline: Introduction states the gap and hypothesis; "
        "Methods must be reproducible; Results report without interpreting; "
        "Discussion interprets without introducing new results.\n"
        "- Flag interpretation leaking into Results and new evidence "
        "appearing in Discussion — the two most common IMRaD faults.\n"
        "- Press for: sample sizes, statistical tests named with assumptions, "
        "effect sizes not just p-values, limitations section.\n"
        "- In challenge modes, ask reviewer-2 questions: confounds, power, "
        "generalisability, whether the conclusion follows from THESE data."
    ),
    "neurips_paper": (
        "DISCIPLINE: machine-learning paper (NeurIPS culture).\n"
        "- Claims-evidence discipline: every capability claim needs a "
        "benchmark, a baseline and an ablation; flag 'state of the art' "
        "without a comparison table.\n"
        "- Reproducibility: seeds, compute budget, hyperparameters, dataset "
        "versions and licences belong in the paper or appendix.\n"
        "- Press for the limitations and broader-impact sections examiners "
        "and reviewers now expect.\n"
        "- In challenge modes: is the improvement within noise, does the "
        "ablation isolate the claimed mechanism, would the result survive a "
        "different dataset split?"
    ),
    "acl_paper": (
        "DISCIPLINE: computational linguistics paper (ACL culture).\n"
        "- Language claims need linguistic evidence: examples glossed and "
        "numbered, error analysis with categories, not just corpus-level "
        "scores.\n"
        "- Press for dataset documentation (source, languages, annotation "
        "agreement) and a qualitative error analysis beside the metrics.\n"
        "- In challenge modes: does the model exploit an artefact, is the "
        "baseline tuned as carefully as the proposal, do the examples in the "
        "paper actually occur in the data?"
    ),
    "cvpr_paper": (
        "DISCIPLINE: computer-vision paper (CVPR culture).\n"
        "- Visual evidence discipline: qualitative figures must be typical, "
        "not cherry-picked — press for failure cases shown alongside "
        "successes.\n"
        "- Benchmarks: standard splits, named metrics, comparisons at equal "
        "compute; flag mixed test protocols.\n"
        "- In challenge modes: dataset bias, does the ablation justify each "
        "architectural claim, inference cost versus the baseline."
    ),
    GENERIC_KEY: (
        "DISCIPLINE: general academic manuscript.\n"
        "- Hold the universal standard: every claim traceable to evidence "
        "the reader can check; methods stated before results; conclusions "
        "no stronger than the evidence.\n"
        "- Respect the manuscript's existing citation convention; note "
        "inconsistencies rather than converting them.\n"
        "- In challenge modes, ask: what is the thesis in one sentence, "
        "which chapter carries the heaviest evidential load, and where "
        "would a skeptical reader stop believing?"
    ),
}

# Guide-playbook keys that differ from profile keys.
_PLAYBOOK_TO_KEY: dict[str, str] = {
    "ma_dissertation": "ma_dissertation",
    "engineering_project_report": "engineering_project_report",
    "imrad_journal_article": "imrad_journal_article",
    "neurips_paper": "neurips_paper",
    "generic": GENERIC_KEY,
}

_DOC_TYPE_TO_KEY: dict[str, str] = {
    "ma_dissertation": "ma_dissertation",
    "mphil_dissertation": "ma_dissertation",
    "phd_thesis": "phd_thesis",
    "project_report": "engineering_project_report",
}


def resolve_domain_key(project: Any) -> str:
    """Layered, total resolution — an unknown value never raises."""
    meta = getattr(project, "meta", None) or {}
    playbook = meta.get("guide_playbook")
    if playbook in _PLAYBOOK_TO_KEY:
        return _PLAYBOOK_TO_KEY[playbook]
    declared = meta.get("domain_profile")
    if declared in DOMAIN_GUIDANCE:
        return declared
    doc_type = getattr(project, "doc_type", None)
    if doc_type in _DOC_TYPE_TO_KEY:
        return _DOC_TYPE_TO_KEY[doc_type]
    return GENERIC_KEY


def guidance_for_project(project: Any) -> tuple[str, str]:
    """(key, guidance text) for the project's discipline."""
    key = resolve_domain_key(project)
    return key, DOMAIN_GUIDANCE[key]
