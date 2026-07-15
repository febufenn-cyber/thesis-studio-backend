"""Provenance rollup — per-origin block counts + accepted-proposal history.

Derives everything from data that already exists: block ``origin`` on the
canonical document (set by the editor/proposal apply paths) and the accepted
``AIProposal`` rows (via ``ai_disclosure_summary``). No new edit-time hook and no
detector — a block whose origin is unknown is reported as such, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.disclosure import ai_disclosure_summary
from app.models.project import Project
from app.services.export_service import build_thesis_document

_ORIGINS = ("human", "ai_proposal", "ai_edited", "manuscript_import", "unknown")


@dataclass(frozen=True)
class ProvenanceRollup:
    origin_counts: dict[str, int]
    total_blocks: int
    assisted: bool
    accepted_proposals: int
    accepted_operations: int
    human_edited_operations: int
    task_modes: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    prompt_versions: list[str] = field(default_factory=list)

    @property
    def ai_block_count(self) -> int:
        return self.origin_counts.get("ai_proposal", 0) + self.origin_counts.get("ai_edited", 0)

    def to_dict(self) -> dict:
        return {
            "origin_counts": self.origin_counts,
            "total_blocks": self.total_blocks,
            "ai_block_count": self.ai_block_count,
            "assisted": self.assisted,
            "accepted_proposals": self.accepted_proposals,
            "accepted_operations": self.accepted_operations,
            "human_edited_operations": self.human_edited_operations,
            "task_modes": self.task_modes,
            "models": self.models,
            "prompt_versions": self.prompt_versions,
        }


def _origin_counts(project: Project) -> tuple[dict[str, int], int]:
    """Walk the canonical document and count each block's authorship origin."""
    document = build_thesis_document(project)
    counts = {origin: 0 for origin in _ORIGINS}
    total = 0
    for chapter in document.chapters:
        for block in chapter.blocks:
            origin = block.origin or "unknown"
            counts[origin] = counts.get(origin, 0) + 1
            total += 1
    for entry in document.front_matter:
        for block in entry.body_blocks:
            origin = block.origin or "unknown"
            counts[origin] = counts.get(origin, 0) + 1
            total += 1
    return {k: v for k, v in counts.items() if v}, total


async def build_rollup(
    db: AsyncSession, project: Project, *, document_version: int
) -> ProvenanceRollup:
    """Aggregate block origins + accepted-proposal history into one rollup."""
    summary = await ai_disclosure_summary(db, project, document_version=document_version)
    counts, total = _origin_counts(project)
    return ProvenanceRollup(
        origin_counts=counts,
        total_blocks=total,
        assisted=bool(summary["assisted"]),
        accepted_proposals=int(summary["accepted_proposals"]),
        accepted_operations=int(summary["accepted_operations"]),
        human_edited_operations=int(summary["human_edited_operations"]),
        task_modes=list(summary["task_modes"]),
        models=list(summary["models"]),
        prompt_versions=list(summary["prompt_versions"]),
    )
