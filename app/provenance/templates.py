"""Disclosure-template registry — render an AI Use Statement from a rollup.

DB-free, mirroring ``app/domains/profiles.py``. Each template maps a rollup to
prose appropriate to a policy regime (a generic university declaration, a
NeurIPS-style disclosure, an Elsevier-style statement). Unknown keys fail closed
(``UnknownDisclosureTemplate``) rather than emitting a generic statement.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.provenance.rollup import ProvenanceRollup


class UnknownDisclosureTemplate(KeyError):
    """The requested disclosure-template key is not registered."""


@dataclass(frozen=True)
class DisclosureTemplate:
    key: str
    label: str
    policy_ref: str
    render: Callable[[ProvenanceRollup, str], str]


def _tools_clause(rollup: ProvenanceRollup) -> str:
    if not rollup.models:
        return "an AI writing assistant"
    return "AI assistance (" + ", ".join(sorted(rollup.models)) + ")"


def _render_generic(rollup: ProvenanceRollup, title: str) -> str:
    if not rollup.assisted:
        return (
            f"No AI-assisted document operations are recorded for “{title}”. "
            "All content was authored by the candidate."
        )
    return (
        f"This work (“{title}”) was prepared with {_tools_clause(rollup)}. "
        f"{rollup.accepted_proposals} assistant proposal(s) comprising "
        f"{rollup.accepted_operations} operation(s) were reviewed and explicitly accepted "
        f"by the candidate; {rollup.human_edited_operations} were further edited by hand. "
        f"Of {rollup.total_blocks} document block(s), {rollup.ai_block_count} originated from "
        "accepted AI proposals and the remainder were human-authored or imported. "
        "Direct quotations could be inserted only from human-verified registry records. "
        "The candidate takes full responsibility for the final text."
    )


def _render_neurips(rollup: ProvenanceRollup, title: str) -> str:
    if not rollup.assisted:
        return (
            "LLMs were not used as a core method, and were not used for writing beyond "
            "routine assistance such as spelling and grammar."
        )
    return (
        "Large language models were used to assist the preparation of this manuscript. "
        f"Assistance ({_tools_clause(rollup)}) produced {rollup.accepted_operations} operation(s) "
        f"across {rollup.accepted_proposals} proposal(s), each individually reviewed and accepted "
        "by the authors, who verified correctness and take full responsibility for the content. "
        "The models were not used to generate novel research claims or to fabricate citations; "
        "all references derive from human-verified registry records."
    )


def _render_elsevier(rollup: ProvenanceRollup, title: str) -> str:
    if not rollup.assisted:
        return (
            "Declaration of generative AI in scientific writing: the authors declare that no "
            "generative AI or AI-assisted technologies were used in the preparation of this work."
        )
    return (
        "Declaration of generative AI in scientific writing: during the preparation of this work "
        f"the author(s) used {_tools_clause(rollup)} in order to improve and structure the "
        "manuscript. Every applied change was reviewed and accepted by the author(s), who take "
        "full responsibility for the content of the publication. No content was published without "
        "human verification, and all citations derive from human-verified registry records."
    )


_TEMPLATES: dict[str, DisclosureTemplate] = {
    t.key: t
    for t in (
        DisclosureTemplate(
            key="generic_university",
            label="Generic university declaration",
            policy_ref="Institutional academic-integrity declaration",
            render=_render_generic,
        ),
        DisclosureTemplate(
            key="neurips",
            label="NeurIPS LLM disclosure",
            policy_ref="NeurIPS LLM policy",
            render=_render_neurips,
        ),
        DisclosureTemplate(
            key="elsevier",
            label="Elsevier generative-AI declaration",
            policy_ref="Elsevier 'Declaration of generative AI in scientific writing'",
            render=_render_elsevier,
        ),
    )
}

_DEFAULT_TEMPLATE_KEY = "generic_university"


def get_disclosure_template(key: str) -> DisclosureTemplate:
    """Return a template, or raise ``UnknownDisclosureTemplate`` (fail closed)."""
    try:
        return _TEMPLATES[key]
    except KeyError as exc:
        raise UnknownDisclosureTemplate(key) from exc


def default_template_key() -> str:
    return _DEFAULT_TEMPLATE_KEY


def list_disclosure_templates() -> list[dict]:
    return [
        {"key": t.key, "label": t.label, "policy_ref": t.policy_ref}
        for t in _TEMPLATES.values()
    ]
