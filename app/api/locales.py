"""Locale catalog and per-project locale selection (docs/LLD.md 3.7)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.renderers.locale.profile import is_registered, list_locales

router = APIRouter(tags=["projects"])


class LocaleRequest(BaseModel):
    locale: str
    name_script: Literal["source", "translit", "both"] = "source"


@router.get("/locales")
async def get_locales(current_user: CurrentUser) -> dict:
    """List supported locales."""
    return {"locales": list_locales(), "default": ""}


@router.patch("/projects/{project_id}/locale")
async def set_project_locale(
    project_id: UUID,
    body: LocaleRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set the project's locale and author-name script policy."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    if body.locale and not is_registered(body.locale):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported locale: {body.locale}",
        )
    meta = dict(project.meta or {})
    meta["locale"] = body.locale
    meta["name_script"] = body.name_script
    project.meta = meta
    project.document_version = (project.document_version or 1) + 1
    await db.commit()
    return {
        "id": str(project.id),
        "locale": body.locale,
        "name_script": body.name_script,
        "document_version": project.document_version,
    }
