"""Supervision & committee API (docs/LLD.md 3.6).

Committee assignment is owner-gated (the candidate owns their project and seats
their committee). Commenting is open to the owner and to active committee members
with content access. Semantic diff compares the current document to a posted base
document. Deny-by-default; foreign project → 404.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.canonical.model import ThesisDocument
from app.collaboration.block_feedback import (
    BlockNotFoundError,
    create_block_comment,
    list_block_comments,
    resolve_comment,
)
from app.collaboration.committee import (
    SupervisionPermission,
    member_has_permission,
)
from app.collaboration.semantic_diff import semantic_diff
from app.db.deps import get_db
from app.models.project import Project
from app.models.supervision import BlockComment, CommitteeMembership
from app.services.export_service import build_thesis_document

router = APIRouter(tags=["supervision"])


class CommitteeAssignRequest(BaseModel):
    user_id: UUID
    committee_role: str
    voting: bool = False
    content_access: bool = True
    position: int = 0


class BlockCommentRequest(BaseModel):
    canonical_block_id: UUID
    body: str
    thread_root_id: UUID | None = None


class DiffRequest(BaseModel):
    base_document: dict


async def _owned_project(db, project_id, user) -> Project:
    return await fetch_owned_project(db, project_id, user.id)


async def _project_for_member(db: AsyncSession, project_id: UUID, user, permission) -> Project:
    """Return the project if the user owns it or holds the committee permission."""
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    if project.user_id == user.id:
        return project
    if await member_has_permission(db, project_id, user.id, permission):
        return project
    # 404 (not 403) to avoid project-existence enumeration.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")


def _membership_dict(m: CommitteeMembership) -> dict:
    return {
        "id": str(m.id),
        "user_id": str(m.user_id),
        "committee_role": m.committee_role,
        "voting": m.voting,
        "content_access": m.content_access,
        "status": m.status,
        "position": m.position,
    }


def _comment_dict(c: BlockComment) -> dict:
    return {
        "id": str(c.id),
        "canonical_block_id": str(c.canonical_block_id),
        "author_id": str(c.author_id),
        "committee_role": c.committee_role,
        "body": c.body,
        "anchor_state": c.anchor_state,
        "status": c.status,
        "thread_root_id": str(c.thread_root_id) if c.thread_root_id else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.post("/projects/{project_id}/committee", status_code=status.HTTP_201_CREATED)
async def assign_committee(
    project_id: UUID,
    body: CommitteeAssignRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await _owned_project(db, project_id, current_user)
    existing = (
        await db.execute(
            select(CommitteeMembership).where(
                CommitteeMembership.project_id == project.id,
                CommitteeMembership.user_id == body.user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.committee_role = body.committee_role
        existing.voting = body.voting
        existing.content_access = body.content_access
        existing.position = body.position
        existing.status = "active"
        membership = existing
    else:
        membership = CommitteeMembership(
            project_id=project.id,
            user_id=body.user_id,
            committee_role=body.committee_role,
            voting=body.voting,
            content_access=body.content_access,
            position=body.position,
            assigned_by=current_user.id,
            status="active",
        )
        db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return _membership_dict(membership)


@router.get("/projects/{project_id}/committee")
async def list_committee(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await _project_for_member(db, project_id, current_user, SupervisionPermission.VIEW_CONTENT)
    rows = list(
        (
            await db.execute(
                select(CommitteeMembership)
                .where(CommitteeMembership.project_id == project.id)
                .order_by(CommitteeMembership.position.asc())
            )
        ).scalars()
    )
    return {"members": [_membership_dict(m) for m in rows]}


@router.post("/projects/{project_id}/block-comments", status_code=status.HTTP_201_CREATED)
async def create_comment(
    project_id: UUID,
    body: BlockCommentRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await _project_for_member(db, project_id, current_user, SupervisionPermission.COMMENT)
    role = None
    if project.user_id != current_user.id:
        from app.collaboration.committee import get_active_membership
        membership = await get_active_membership(db, project.id, current_user.id)
        role = membership.committee_role if membership else None
    try:
        comment = await create_block_comment(
            db, project, author_id=current_user.id,
            canonical_block_id=body.canonical_block_id, body=body.body,
            thread_root_id=body.thread_root_id, committee_role=role,
        )
    except BlockNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No such block in the document: {exc.args[0]}",
        ) from exc
    await db.commit()
    await db.refresh(comment)
    return _comment_dict(comment)


@router.get("/projects/{project_id}/block-comments")
async def get_comments(
    project_id: UUID,
    current_user: CurrentUser,
    block_id: UUID | None = None,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await _project_for_member(db, project_id, current_user, SupervisionPermission.VIEW_CONTENT)
    comments = await list_block_comments(db, project, block_id=block_id, status=status_filter)
    await db.commit()
    return {"comments": [_comment_dict(c) for c in comments]}


@router.patch("/projects/{project_id}/block-comments/{comment_id}")
async def resolve_block_comment(
    project_id: UUID,
    comment_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    comment = (
        await db.execute(
            select(BlockComment).where(
                BlockComment.id == comment_id, BlockComment.project_id == project_id
            )
        )
    ).scalar_one_or_none()
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")

    is_owner = project.user_id == current_user.id
    is_author = comment.author_id == current_user.id
    can_resolve_any = await member_has_permission(
        db, project_id, current_user.id, SupervisionPermission.RESOLVE_ANY
    )
    if not (is_owner or is_author or can_resolve_any):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")

    await resolve_comment(db, comment, current_user.id)
    await db.commit()
    await db.refresh(comment)
    return _comment_dict(comment)


@router.post("/projects/{project_id}/diff")
async def project_diff(
    project_id: UUID,
    body: DiffRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Semantic diff of the current document against a posted base document."""
    project = await _project_for_member(db, project_id, current_user, SupervisionPermission.VIEW_CONTENT)
    head = build_thesis_document(project)
    try:
        base = ThesisDocument.model_validate(body.base_document)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base document."
        ) from exc
    result = semantic_diff(base, head)
    return result.to_dict()
