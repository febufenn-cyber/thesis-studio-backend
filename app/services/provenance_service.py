"""Provenance service — generate/read AI Use Statements and the timeline."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collaboration.workflow import canonical_checksum
from app.models.ai_proposal import AIProposal
from app.models.ai_use_statement import AIUseStatement
from app.models.document_command import DocumentCommand
from app.models.project import Project
from app.provenance.rollup import ProvenanceRollup, build_rollup
from app.provenance.templates import default_template_key, get_disclosure_template


def _content_hash(body_text: str, document_checksum: str) -> str:
    return hashlib.sha256(f"{body_text}\x00{document_checksum}".encode()).hexdigest()


async def generate_ai_use_statement(
    db: AsyncSession,
    project: Project,
    *,
    template_key: str | None = None,
    granularity: str = "document",
    generated_by: UUID | None = None,
) -> AIUseStatement:
    """Render and persist an AI Use Statement for the project's current version."""
    key = template_key or (project.meta or {}).get("disclosure_template_key") or default_template_key()
    template = get_disclosure_template(key)  # fail-closed on unknown key

    rollup: ProvenanceRollup = await build_rollup(
        db, project, document_version=project.document_version
    )
    title = (project.meta or {}).get("title") or "this work"
    body_text = template.render(rollup, title)
    checksum = canonical_checksum(project)
    statement = AIUseStatement(
        project_id=project.id,
        document_version=project.document_version,
        document_checksum=checksum,
        template_key=key,
        granularity=granularity,
        body_text=body_text,
        rollup=rollup.to_dict(),
        content_hash=_content_hash(body_text, checksum),
        generated_by=generated_by,
    )
    db.add(statement)
    await db.flush()
    return statement


async def get_latest_statement(
    db: AsyncSession, project: Project, *, document_version: int | None = None
) -> AIUseStatement | None:
    """Return the most recent statement, optionally for a specific version."""
    query = select(AIUseStatement).where(AIUseStatement.project_id == project.id)
    if document_version is not None:
        query = query.where(AIUseStatement.document_version == document_version)
    query = query.order_by(desc(AIUseStatement.created_at)).limit(1)
    return (await db.execute(query)).scalar_one_or_none()


async def get_provenance_timeline(
    db: AsyncSession, project: Project, *, document_version: int | None = None
) -> list[dict]:
    """Ordered accepted-proposal events for the project (authorship transitions)."""
    version = document_version if document_version is not None else project.document_version
    rows = list(
        (
            await db.execute(
                select(AIProposal, DocumentCommand)
                .join(DocumentCommand, DocumentCommand.id == AIProposal.applied_command_id)
                .where(
                    AIProposal.project_id == project.id,
                    AIProposal.status.in_(("accepted", "partially_accepted")),
                    AIProposal.applied_command_id.is_not(None),
                    DocumentCommand.document_version_after <= version,
                )
                .order_by(DocumentCommand.document_version_after.asc())
            )
        ).all()
    )
    events: list[dict] = []
    for proposal, command in rows:
        events.append(
            {
                "proposal_id": str(proposal.id),
                "command_id": str(command.id),
                "task_mode": proposal.task_mode,
                "model": proposal.model,
                "prompt_version": f"{proposal.prompt_name}:{proposal.prompt_version}",
                "status": proposal.status,
                "accepted_operations": len(proposal.selected_operation_indexes or []),
                "human_edited_operations": len(proposal.human_edited_operations or {}),
                "document_version_after": command.document_version_after,
            }
        )
    return events
