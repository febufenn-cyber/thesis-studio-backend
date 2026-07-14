"""Block-anchored feedback (docs/LLD.md 3.6).

Comments anchor to a canonical block id, not a text offset, so they survive
re-rendering and re-styling. On read, the anchor state is recomputed: the block
is present and unchanged (``current``), present but edited (``block_changed``),
or gone (``orphaned``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collaboration.workflow import block_text, find_block
from app.models.project import Project
from app.models.supervision import BlockComment


class BlockNotFoundError(ValueError):
    """The comment's target block id does not exist in the document."""


async def create_block_comment(
    db: AsyncSession,
    project: Project,
    *,
    author_id: UUID,
    canonical_block_id: UUID,
    body: str,
    thread_root_id: UUID | None = None,
    committee_role: str | None = None,
) -> BlockComment:
    found = find_block(project, canonical_block_id)
    if found is None:
        raise BlockNotFoundError(str(canonical_block_id))
    scope_id, block = found
    comment = BlockComment(
        project_id=project.id,
        canonical_block_id=canonical_block_id,
        scope_id=scope_id,
        thread_root_id=thread_root_id,
        author_id=author_id,
        committee_role=committee_role,
        body=body,
        block_text_snapshot=block_text(block),
        first_seen_document_version=project.document_version,
        anchor_state="current",
    )
    db.add(comment)
    await db.flush()
    return comment


def _anchor_state(project: Project, comment: BlockComment) -> str:
    found = find_block(project, comment.canonical_block_id)
    if found is None:
        return "orphaned"
    _scope, block = found
    if block_text(block) == (comment.block_text_snapshot or ""):
        return "current"
    return "block_changed"


async def list_block_comments(
    db: AsyncSession,
    project: Project,
    *,
    block_id: UUID | None = None,
    status: str | None = None,
) -> list[BlockComment]:
    query = select(BlockComment).where(BlockComment.project_id == project.id)
    if block_id is not None:
        query = query.where(BlockComment.canonical_block_id == block_id)
    if status is not None:
        query = query.where(BlockComment.status == status)
    query = query.order_by(BlockComment.created_at.asc())
    comments = list((await db.execute(query)).scalars())
    for comment in comments:
        state = _anchor_state(project, comment)
        if state != comment.anchor_state:
            comment.anchor_state = state
    await db.flush()
    return comments


async def resolve_comment(db: AsyncSession, comment: BlockComment, user_id: UUID) -> BlockComment:
    comment.status = "resolved"
    comment.resolved_by = user_id
    comment.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return comment
