"""AI provenance summaries for export manifests and disclosure pages."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_proposal import AIProposal
from app.models.document_command import DocumentCommand
from app.models.project import Project


async def ai_disclosure_summary(
    db: AsyncSession,
    project: Project,
    *,
    document_version: int,
) -> dict:
    rows = list(
        (
            await db.execute(
                select(AIProposal, DocumentCommand)
                .join(DocumentCommand, DocumentCommand.id == AIProposal.applied_command_id)
                .where(
                    AIProposal.project_id == project.id,
                    AIProposal.user_id == project.user_id,
                    AIProposal.status.in_(("accepted", "partially_accepted")),
                    AIProposal.applied_command_id.is_not(None),
                    DocumentCommand.document_version_after <= document_version,
                )
                .order_by(AIProposal.created_at.asc())
            )
        ).all()
    )
    proposal_ids: list[str] = []
    command_ids: list[str] = []
    modes: set[str] = set()
    models: set[str] = set()
    prompt_versions: set[str] = set()
    accepted_operations = 0
    human_edited_operations = 0
    for proposal, command in rows:
        proposal_ids.append(str(proposal.id))
        command_ids.append(str(command.id))
        modes.add(proposal.task_mode)
        models.add(proposal.model)
        prompt_versions.add(f"{proposal.prompt_name}:{proposal.prompt_version}")
        accepted_operations += len(proposal.selected_operation_indexes or [])
        human_edited_operations += len(proposal.human_edited_operations or {})

    assisted = bool(rows)
    policy = project.ai_policy or {}
    statement = (
        "Robofox Scholar was used for structured academic assistance. Every applied operation "
        "was selected by the user and passed through version checks, undo history and deterministic verification. "
        "Direct quotations could be inserted only from human-verified registry records."
        if assisted
        else "No accepted Robofox Scholar document operations are recorded for this document version."
    )
    return {
        "assisted": assisted,
        "disclosure_required": bool(policy.get("disclosure_required", True)),
        "accepted_proposals": len(rows),
        "accepted_operations": accepted_operations,
        "human_edited_operations": human_edited_operations,
        "task_modes": sorted(modes),
        "models": sorted(models),
        "prompt_versions": sorted(prompt_versions),
        "proposal_ids": proposal_ids,
        "command_ids": command_ids,
        "statement": statement,
        "raw_private_conversations_included": False,
        "truth_notice": (
            "Internal verification confirms traceability, not universal truth, originality, "
            "source credibility or intellectual validity."
        ),
    }
