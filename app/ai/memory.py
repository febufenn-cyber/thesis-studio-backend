"""Hierarchical project memory that remains subordinate to canonical content."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import MemoryUpdate
from app.models.ai_memory import AIMemory
from app.models.ai_message import AIMessage
from app.models.ai_thread import AIThread
from app.models.message import Message
from app.models.project import Project
from app.models.session import ThesisSession


async def upsert_memory_updates(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    updates: list[MemoryUpdate],
    *,
    prompt_version: str,
    model: str,
) -> list[AIMemory]:
    rows: list[AIMemory] = []
    valid_chapter_ids = {str(item.get("id")) for item in project.chapters or []}
    for item in updates:
        if item.scope_type == "chapter" and item.scope_key not in valid_chapter_ids:
            continue
        row = (
            await db.execute(
                select(AIMemory).where(
                    AIMemory.project_id == project.id,
                    AIMemory.user_id == user_id,
                    AIMemory.scope_type == item.scope_type,
                    AIMemory.scope_key == item.scope_key,
                    AIMemory.kind == item.kind,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = AIMemory(
                project_id=project.id,
                user_id=user_id,
                scope_type=item.scope_type,
                scope_key=item.scope_key,
                kind=item.kind,
                content=item.content,
                based_on_document_version=project.document_version,
                generated_by="ai",
                prompt_version=prompt_version,
                model=model,
                stale=False,
            )
            db.add(row)
        else:
            row.content = item.content
            row.based_on_document_version = project.document_version
            row.generated_by = "ai"
            row.prompt_version = prompt_version
            row.model = model
            row.stale = False
        rows.append(row)
    await db.flush()
    return rows


async def mark_old_memories_stale(db: AsyncSession, project: Project) -> None:
    await db.execute(
        update(AIMemory)
        .where(
            AIMemory.project_id == project.id,
            AIMemory.based_on_document_version != project.document_version,
        )
        .values(stale=True)
    )


async def link_legacy_session(
    db: AsyncSession,
    project: Project,
    session: ThesisSession,
    user_id: UUID,
) -> AIThread:
    """Link historical coaching without giving its fields canonical authority."""

    if session.user_id != user_id or project.user_id != user_id:
        raise ValueError("Session and project must belong to the same user.")
    existing = (
        await db.execute(
            select(AIThread).where(
                AIThread.project_id == project.id,
                AIThread.user_id == user_id,
                AIThread.legacy_session_id == session.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        session.project_id = project.id
        await db.commit()
        return existing

    thread = AIThread(
        project_id=project.id,
        user_id=user_id,
        legacy_session_id=session.id,
        title=f"Legacy coaching — {session.title}",
        scope={"type": "project"},
        private=True,
    )
    db.add(thread)
    await db.flush()

    historical = {
        "notice": "Historical coaching context only. Canonical Project content and current project policy override these values.",
        "phase": session.phase,
        "primary_text": session.primary_text,
        "subfield": session.subfield,
        "framework": session.framework,
        "thesis_statement": session.thesis_statement,
        "outline": session.outline_json,
        "supervisor_name": session.supervisor_full_name,
        "supervisor_designation": session.supervisor_designation,
    }
    memory = AIMemory(
        project_id=project.id,
        user_id=user_id,
        scope_type="project",
        scope_key=f"legacy:{session.id}",
        kind="legacy_context",
        content=historical,
        based_on_document_version=project.document_version,
        generated_by="legacy_import",
        stale=False,
    )
    db.add(memory)

    messages = list(
        (
            await db.execute(
                select(Message).where(Message.session_id == session.id).order_by(Message.created_at.asc())
            )
        ).scalars()
    )
    for message in messages:
        db.add(
            AIMessage(
                thread_id=thread.id,
                project_id=project.id,
                user_id=user_id,
                role=message.role,
                task_mode=None,
                content=message.content,
                structured={"legacy_message_id": str(message.id)},
                scope={"type": "project", "legacy": True},
                document_version=project.document_version,
                model=message.model,
                prompt_name="legacy_coaching_history",
                prompt_version="legacy",
                context_manifest={"legacy_session_id": str(session.id)},
                usage={
                    "input_tokens": message.input_tokens,
                    "output_tokens": message.output_tokens,
                    "cached_input_tokens": message.cached_input_tokens,
                },
                created_at=message.created_at,
            )
        )
    session.project_id = project.id
    await db.commit()
    await db.refresh(thread)
    return thread
