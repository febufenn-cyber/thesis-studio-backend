"""Per-domain start-from-zero playbooks.

Each playbook gives a student with NO draft a structured path: topic-selection
worksheet, methodology guidance, suggested source types, and a chapter
skeleton the scaffold endpoint can create. Playbooks are guidance, never
content: skeleton blocks carry clearly-marked [TO WRITE] prompts — questions
the student answers — and nothing that could be mistaken for finished prose or
invented facts (never-guess applies to templates too).

Keys align with app/domains/profiles.py so validators and citation styles
follow the same choice.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Playbook:
    key: str
    label: str
    audience: str
    citation_hint: str
    topic_worksheet: list = field(default_factory=list)
    methodology: list = field(default_factory=list)
    source_types: list = field(default_factory=list)
    skeleton: list = field(default_factory=list)  # (number, title, [TO WRITE] prompts)
    checklist: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


_LIT = Playbook(
    key="ma_dissertation",
    label="Literature / Humanities (MA dissertation)",
    audience="MA English and humanities students writing a text-based dissertation",
    citation_hint="MLA 9 (parenthetical author-page, Works Cited)",
    topic_worksheet=[
        "Which primary text(s) keep pulling you back? List 2-3 candidates.",
        "What puzzles you about them — a contradiction, a silence, a technique?",
        "Name the conversation: which 2-3 critics have written closest to your puzzle?",
        "Draft a one-sentence claim: '<Text> uses <technique> to <effect>, which shows <argument>.'",
        "Feasibility check: can you access the primary text, 10+ secondary sources, and finish in your timeline?",
    ],
    methodology=[
        "Close reading: anchor every claim in quoted passages with page numbers.",
        "Frame with ONE critical lens (narratology, memory studies, postcolonial...) — name it in Chapter 1.",
        "Each body chapter = one movement of the argument, not one summary of a text.",
    ],
    source_types=[
        "Primary text(s) — the edition matters; record it first.",
        "Peer-reviewed criticism (journals, edited collections).",
        "One or two theory anchors for your lens.",
    ],
    skeleton=[
        (1, "Introduction", [
            "State your research problem in 2-3 sentences.",
            "Name your primary text(s) and edition.",
            "State your claim (thesis statement) — one sentence.",
            "Preview each chapter's role in the argument.",
        ]),
        (2, "Review of Literature", [
            "Summarize the critical conversation your thesis joins.",
            "Identify the gap your argument fills.",
        ]),
        (3, "Analysis I", ["First movement of your argument, anchored in close reading."]),
        (4, "Analysis II", ["Second movement — complication or counter-case."]),
        (5, "Conclusion", ["Restate what the analysis established; name its limits and openings."]),
    ],
    checklist=[
        "Primary text added to the source registry",
        "10+ secondary sources imported (BibTeX/Zotero or search)",
        "Every quotation entered through the quote registry",
        "Chapter 1 states the claim explicitly",
    ],
)

_ENG = Playbook(
    key="engineering_project_report",
    label="Engineering (project report)",
    audience="UG/PG engineering students reporting a built project",
    citation_hint="IEEE numeric citations",
    topic_worksheet=[
        "What problem does your project solve, for whom?",
        "What exists already (3 existing systems/papers) and what's wrong with each?",
        "What is YOUR delta — the one improvement you can demonstrate?",
        "What can you measure to prove the delta (metric, dataset, testbench)?",
        "Feasibility: parts/tools available? Demo possible before the deadline?",
    ],
    methodology=[
        "Requirements → design → implementation → testing: keep the chain traceable.",
        "Define evaluation metrics BEFORE building; report against them honestly.",
        "Every figure/table needs a source: your measurement or a cited one.",
    ],
    source_types=[
        "IEEE/ACM papers for the state of the art.",
        "Datasheets and standards for components.",
        "Datasets/benchmarks with proper citation.",
    ],
    skeleton=[
        (1, "Introduction", ["Problem statement, motivation, objectives, scope."]),
        (2, "Literature Survey", ["Existing systems and their limitations — cite each."]),
        (3, "System Design", ["Architecture, modules, design decisions and trade-offs."]),
        (4, "Implementation", ["Tools, key algorithms, build details."]),
        (5, "Results and Discussion", ["Metrics, test results, comparison with objectives."]),
        (6, "Conclusion and Future Work", ["What was achieved; honest limitations; next steps."]),
    ],
    checklist=[
        "Objectives measurable and stated in Chapter 1",
        "Every existing-system claim carries a citation",
        "Results reported against the declared metrics",
    ],
)

_SCI = Playbook(
    key="imrad_journal_article",
    label="Sciences (IMRaD thesis/article)",
    audience="Science students writing hypothesis-driven research",
    citation_hint="APA / Vancouver depending on department",
    topic_worksheet=[
        "State your research question as a testable hypothesis.",
        "What would DISPROVE it? If nothing could, sharpen the question.",
        "What data/experiment can you actually run with available equipment?",
        "Which 3 recent papers are closest? What does each leave open?",
    ],
    methodology=[
        "Methods must be reproducible: another student should be able to repeat them.",
        "Pre-state sample sizes, controls and analysis before collecting data.",
        "Report negative results honestly — they are results.",
    ],
    source_types=[
        "Recent peer-reviewed articles (last 5 years weighted).",
        "Methods papers for your techniques.",
        "Datasets/protocols with DOIs.",
    ],
    skeleton=[
        (1, "Introduction", ["Background, gap, hypothesis and objectives."]),
        (2, "Materials and Methods", ["Design, materials, procedure, analysis plan."]),
        (3, "Results", ["Findings only — no interpretation yet."]),
        (4, "Discussion", ["Interpretation, comparison with literature, limitations."]),
        (5, "Conclusion", ["What the evidence supports; future work."]),
    ],
    checklist=[
        "Hypothesis falsifiable and stated in Chapter 1",
        "Methods detailed enough to reproduce",
        "Every comparison claim cites its source",
    ],
)

_CS = Playbook(
    key="neurips_paper",
    label="Computer Science / ML (conference-style)",
    audience="CS/ML students writing an experimental paper or thesis",
    citation_hint="ACL/NeurIPS author-year",
    topic_worksheet=[
        "One-sentence contribution: 'We show that X improves Y by Z on W.'",
        "Baseline check: what's the strongest existing method you must beat or match?",
        "Compute/data reality check: can you run the experiments you're promising?",
        "Ablation plan: which components will you isolate to prove WHY it works?",
    ],
    methodology=[
        "Fix seeds, report variance, state hardware — reproducibility is the methodology.",
        "Compare against real baselines, not strawmen.",
        "Negative/failed ablations belong in the paper.",
    ],
    source_types=[
        "arXiv + conference papers (resolve DOIs/arXiv IDs in the registry).",
        "Benchmark datasets with versions.",
        "Code/artifact citations where used.",
    ],
    skeleton=[
        (1, "Introduction", ["Contribution statement, motivation, summary of results."]),
        (2, "Related Work", ["Group by approach; state your delta from each group."]),
        (3, "Method", ["Formal description; assumptions; complexity."]),
        (4, "Experiments", ["Setup, baselines, metrics, results, ablations."]),
        (5, "Conclusion", ["Claims supported; limitations; broader impact."]),
    ],
    checklist=[
        "Contribution sentence finalized",
        "Baselines implemented/cited",
        "Experimental setup reproducible (seeds, versions, hardware)",
    ],
)

_GENERIC = Playbook(
    key="generic",
    label="Any other subject (generic research plan)",
    audience="Any student starting a supervised research project from zero",
    citation_hint="Follow your department's prescribed style",
    topic_worksheet=[
        "List 3 topics you could sustain interest in for months.",
        "For each: is there enough published literature to converse with?",
        "For each: what would the finished contribution LOOK like (argument, artifact, experiment)?",
        "Pick the one where interest, literature and feasibility overlap; write its one-sentence aim.",
    ],
    methodology=[
        "Choose a method you can defend: why THIS way of answering the question?",
        "Plan backwards from the deadline: data/reading done by when, drafts by when?",
    ],
    source_types=[
        "Peer-reviewed literature for the core conversation.",
        "Primary materials (texts, data, archives) your field requires.",
    ],
    skeleton=[
        (1, "Introduction", ["Research problem, aim, significance, chapter preview."]),
        (2, "Literature Review", ["The conversation and the gap."]),
        (3, "Methodology", ["Your method and why it fits the question."]),
        (4, "Analysis / Findings", ["The core work."]),
        (5, "Conclusion", ["Contribution, limitations, future directions."]),
    ],
    checklist=[
        "Aim stated in one sentence",
        "10+ sources in the registry",
        "Methodology chapter names its method explicitly",
    ],
)

_PLAYBOOKS: dict[str, Playbook] = {p.key: p for p in (_LIT, _ENG, _SCI, _CS, _GENERIC)}


def list_playbooks() -> list[dict]:
    return [p.to_dict() for p in _PLAYBOOKS.values()]


def get_playbook(key: str) -> Playbook | None:
    return _PLAYBOOKS.get(key)
