"""Persistent Phase 2 review inbox and transparent readiness endpoints."""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.models.review_item import ReviewItem
from app.schemas.editor import ReviewItemResponse, ReviewResolveRequest
from app.services.review_service import (
    ReviewResolutionError,
    resolve_review_item,
    sync_review_items,
)


router = APIRouter(tags=["phase2-review"])


@router.get(
    "/projects/{project_id}/review-items",
    response_model=list[ReviewItemResponse],
)
async def list_review_items(
    project_id: UUID,
    current_user: CurrentUser,
    status: str | None = Query(None),
    severity: str | None = Query(None),
    category: str | None = Query(None),
    block_id: UUID | None = Query(None),
    refresh: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    if refresh:
        rows, _report, _readiness = await sync_review_items(db, project)
        await db.commit()
    else:
        query = select(ReviewItem).where(
            ReviewItem.project_id == project.id,
            ReviewItem.user_id == current_user.id,
        )
        rows = list((await db.execute(query)).scalars())
    if status:
        rows = [row for row in rows if row.status == status]
    if severity:
        rows = [row for row in rows if row.severity == severity]
    if category:
        rows = [row for row in rows if row.category == category]
    if block_id:
        rows = [row for row in rows if row.block_id == block_id]
    order = {"block": 0, "warn": 1, "info": 2}
    return sorted(
        rows,
        key=lambda row: (
            1 if row.status in {"resolved", "acknowledged", "superseded"} else 0,
            order.get(row.severity, 9),
            row.created_at,
        ),
    )


@router.get("/projects/{project_id}/readiness")
async def project_readiness(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    rows, report, readiness = await sync_review_items(db, project)
    await db.commit()
    open_rows = [row for row in rows if row.status == "open"]
    return {
        "document_version": project.document_version,
        "ready": readiness["ready"],
        "readiness": readiness,
        "verification_counts": report.get("counts", {}),
        "open_review_items": len(open_rows),
        "by_category": dict(Counter(row.category for row in open_rows)),
        "by_severity": dict(Counter(row.severity for row in open_rows)),
        "profile": report.get("profile"),
        "profile_version": report.get("profile_version"),
        "profile_notes": report.get("profile_notes"),
        "active_sources": report.get("active_sources", 0),
        "active_quotes": report.get("active_quotes", 0),
    }


@router.get(
    "/projects/{project_id}/review-items/{item_id}",
    response_model=ReviewItemResponse,
)
async def get_review_item(
    project_id: UUID,
    item_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await fetch_owned_project(db, project_id, current_user.id)
    item = (
        await db.execute(
            select(ReviewItem).where(
                ReviewItem.id == item_id,
                ReviewItem.project_id == project_id,
                ReviewItem.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return item


@router.patch(
    "/projects/{project_id}/review-items/{item_id}",
    response_model=ReviewItemResponse,
)
async def update_review_item(
    project_id: UUID,
    item_id: UUID,
    body: ReviewResolveRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    item = (
        await db.execute(
            select(ReviewItem).where(
                ReviewItem.id == item_id,
                ReviewItem.project_id == project.id,
                ReviewItem.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    try:
        return await resolve_review_item(
            db,
            project,
            current_user.id,
            item,
            action=body.action,
            note=body.note,
            expected_version=body.expected_document_version,
        )
    except ReviewResolutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
