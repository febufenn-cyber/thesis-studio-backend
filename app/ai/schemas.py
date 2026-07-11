"""Strict schemas for AI requests, outputs, proposals and human decisions."""

from __future__ import annotations

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


ScopeType = Literal["project", "chapter", "selection", "block", "review", "source", "quote"]
TaskMode = Literal[
    "understand", "diagnose", "plan", "transform", "challenge", "research",
    "coherence", "viva", "memory_refresh",
]
RiskLevel = Literal["low", "medium", "high"]
OperationKind = Literal[
    "replace_runs", "insert_paragraph", "insert_marker", "move_block", "add_verified_quote"
]
_LONG_DIRECT_QUOTE = re.compile(
    r'(?:"[^"\n]{20,}"|“[^”\n]{20,}”|‘[^’\n]{20,}’|\'[^\'\n]{20,}\')'
)


class AIScope(BaseModel):
    type: ScopeType = "project"
    chapter_id: UUID | None = None
    block_id: UUID | None = None
    block_ids: list[UUID] = Field(default_factory=list, max_length=50)
    review_item_id: UUID | None = None
    source_id: UUID | None = None
    quote_id: UUID | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def required_anchor(self):
        required = {
            "chapter": self.chapter_id,
            "block": self.block_id,
            "review": self.review_item_id,
            "source": self.source_id,
            "quote": self.quote_id,
        }
        if self.type in required and required[self.type] is None:
            raise ValueError(f"scope type {self.type!r} requires its stable id")
        if self.type == "selection" and not self.block_ids:
            raise ValueError("selection scope requires at least one block id")
        return self


class AIRequest(BaseModel):
    thread_id: UUID | None = None
    task_mode: TaskMode
    prompt: str = Field(..., min_length=2, max_length=12_000)
    scope: AIScope = Field(default_factory=AIScope)
    expected_document_version: int = Field(..., ge=1)
    client_request_id: str | None = Field(None, min_length=8, max_length=120)

    model_config = {"extra": "forbid"}


class AIOperation(BaseModel):
    kind: OperationKind
    label: str = Field(..., min_length=2, max_length=180)
    reason: str = Field(..., min_length=2, max_length=1200)
    risk: RiskLevel = "medium"
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def direct_quotes_require_registry_ids(self):
        if self.kind not in {"replace_runs", "insert_paragraph"}:
            return self
        text = str(self.payload.get("text", ""))
        if isinstance(self.payload.get("runs"), list):
            text += "".join(
                str(run.get("text", ""))
                for run in self.payload["runs"]
                if isinstance(run, dict)
            )
        if _LONG_DIRECT_QUOTE.search(text):
            raise ValueError(
                "Direct quotation text cannot be supplied in a prose operation. "
                "Use add_verified_quote with a human-verified quote_id or insert a marker."
            )
        return self


class EvidenceSummary(BaseModel):
    source_ids: list[UUID] = Field(default_factory=list)
    quote_ids: list[UUID] = Field(default_factory=list)
    evidence_types: list[
        Literal[
            "direct_quotation", "paraphrase", "summary", "primary_text_observation",
            "critical_interpretation", "contextual_fact",
        ]
    ] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class AIProposalPayload(BaseModel):
    rationale: str = Field(..., min_length=2, max_length=6000)
    explanation: str = Field(..., min_length=2, max_length=6000)
    operations: list[AIOperation] = Field(default_factory=list, max_length=20)
    evidence: EvidenceSummary = Field(default_factory=EvidenceSummary)
    assumptions: list[str] = Field(default_factory=list, max_length=30)
    unresolved_requirements: list[str] = Field(default_factory=list, max_length=30)

    model_config = {"extra": "forbid"}


class MemoryUpdate(BaseModel):
    scope_type: Literal["project", "chapter", "section"]
    scope_key: str = Field(..., min_length=1, max_length=100)
    kind: Literal["summary", "argument_map", "voice_profile", "literature_matrix"]
    content: dict[str, Any]

    model_config = {"extra": "forbid"}


class ResearchQuery(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    purpose: str = Field(..., min_length=2, max_length=800)
    suggested_indexes: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class VivaQuestion(BaseModel):
    question: str = Field(..., min_length=3, max_length=1200)
    why_asked: str = Field(..., min_length=2, max_length=1200)
    evidence_to_review: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class GroundedAIOutput(BaseModel):
    response_text: str = Field(..., min_length=1, max_length=40_000)
    analysis: dict[str, Any] = Field(default_factory=dict)
    proposal: AIProposalPayload | None = None
    memory_updates: list[MemoryUpdate] = Field(default_factory=list, max_length=30)
    research_queries: list[ResearchQuery] = Field(default_factory=list, max_length=20)
    viva_questions: list[VivaQuestion] = Field(default_factory=list, max_length=30)

    model_config = {"extra": "forbid"}


class ProposalDecision(BaseModel):
    action: Literal["accept_selected", "accept_all", "reject", "supersede"]
    selected_operation_indexes: list[int] = Field(default_factory=list, max_length=20)
    operation_overrides: dict[int, AIOperation] = Field(default_factory=dict)
    expected_document_version: int = Field(..., ge=1)
    decision_note: str | None = Field(None, max_length=4000)
    rejection_reason: Literal[
        "changes_meaning", "voice_mismatch", "unsupported_claim", "incorrect_source_use",
        "too_verbose", "too_generic", "supervisor_conflict", "wrong_interpretation",
        "useful_idea_poor_wording", "other",
    ] | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_decision(self):
        if self.action == "accept_selected" and not self.selected_operation_indexes:
            raise ValueError("accept_selected requires at least one operation index")
        if self.action == "reject" and not self.rejection_reason:
            raise ValueError("rejection_reason is required when rejecting a proposal")
        if self.operation_overrides and self.action not in {"accept_selected", "accept_all"}:
            raise ValueError("operation overrides are valid only while accepting a proposal")
        return self
