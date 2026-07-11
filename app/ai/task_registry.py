"""Versioned task registry and server-side model/risk routing."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai import PROMPT_BUNDLE_VERSION
from app.core.config import get_settings


@dataclass(frozen=True)
class TaskSpec:
    mode: str
    prompt_name: str
    prompt_version: str
    result_type: str
    risk_level: str
    model_tier: str
    allowed_operations: tuple[str, ...]
    maximum_scope: str
    description: str


TASKS: dict[str, TaskSpec] = {
    "understand": TaskSpec(
        "understand", "selected_scope_explanation", PROMPT_BUNDLE_VERSION,
        "conversation", "low", "utility", (), "chapter",
        "Explain or summarise selected canonical content without proposing a mutation.",
    ),
    "diagnose": TaskSpec(
        "diagnose", "evidence_and_argument_diagnosis", PROMPT_BUNDLE_VERSION,
        "analysis", "low", "reasoning", (), "chapter",
        "Identify claim, evidence, analysis, transition and traceability weaknesses.",
    ),
    "plan": TaskSpec(
        "plan", "revision_plan", PROMPT_BUNDLE_VERSION,
        "proposal", "medium", "reasoning",
        ("insert_marker", "insert_paragraph", "move_block"), "chapter",
        "Propose a reviewable revision sequence without silently rewriting content.",
    ),
    "transform": TaskSpec(
        "transform", "bounded_text_transformation", PROMPT_BUNDLE_VERSION,
        "proposal", "medium", "reasoning",
        ("replace_runs", "insert_paragraph", "insert_marker", "add_verified_quote"),
        "selection",
        "Propose bounded prose changes while preserving meaning and evidence links.",
    ),
    "challenge": TaskSpec(
        "challenge", "skeptical_examiner", PROMPT_BUNDLE_VERSION,
        "conversation", "low", "reasoning", (), "chapter",
        "Challenge the argument and ask defence-oriented questions.",
    ),
    "research": TaskSpec(
        "research", "controlled_research_queries", PROMPT_BUNDLE_VERSION,
        "research", "low", "utility", (), "project",
        "Generate search strategies and candidate metadata only; no external browsing or verification.",
    ),
    "coherence": TaskSpec(
        "coherence", "whole_thesis_coherence", PROMPT_BUNDLE_VERSION,
        "analysis", "medium", "strong", (), "project",
        "Compare thesis, chapter claims, terminology, evidence and conclusion for drift.",
    ),
    "viva": TaskSpec(
        "viva", "defence_readiness", PROMPT_BUNDLE_VERSION,
        "conversation", "low", "strong", (), "chapter",
        "Generate evidence-grounded viva questions and self-diagnostic prompts; never grade.",
    ),
    "memory_refresh": TaskSpec(
        "memory_refresh", "hierarchical_memory_refresh", PROMPT_BUNDLE_VERSION,
        "memory", "low", "utility", (), "project",
        "Refresh project/chapter summaries, the thesis argument map and literature-review matrix without changing the document.",
    ),
}


def get_task(mode: str) -> TaskSpec:
    try:
        return TASKS[mode]
    except KeyError as exc:
        raise ValueError(f"Unsupported AI task mode: {mode}") from exc


def model_for(spec: TaskSpec) -> str:
    settings = get_settings()
    if spec.model_tier == "utility":
        return settings.CLAUDE_UTILITY_MODEL
    if spec.model_tier == "strong":
        return settings.CLAUDE_COMPILE_MODEL
    return settings.CLAUDE_COACHING_MODEL


def public_task_catalog() -> list[dict]:
    return [
        {
            "mode": spec.mode,
            "description": spec.description,
            "result_type": spec.result_type,
            "risk_level": spec.risk_level,
            "maximum_scope": spec.maximum_scope,
        }
        for spec in TASKS.values()
    ]
