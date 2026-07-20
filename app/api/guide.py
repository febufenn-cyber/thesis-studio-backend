"""Robofox guide API — start-from-zero journeys.

Playbooks are per-domain planning guidance (topic worksheet, methodology,
skeleton). The scaffold endpoint turns a playbook into a real chapter
skeleton whose blocks are clearly-marked [TO WRITE] prompts — questions for
the student, never invented prose. It refuses to overwrite existing chapters.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.canonical.model import ChapterDoc
from app.db.deps import get_db
from app.guide.playbooks import get_playbook, list_playbooks

router = APIRouter(tags=["guide"])


class ScaffoldRequest(BaseModel):
    playbook: str


@router.get("/guide/playbooks")
async def playbooks(current_user: CurrentUser) -> dict:
    """All start-from-zero playbooks (per academic domain)."""
    return {"playbooks": list_playbooks()}


@router.post("/projects/{project_id}/guide/scaffold", status_code=status.HTTP_201_CREATED)
async def scaffold_project(
    project_id: UUID,
    body: ScaffoldRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create the playbook's chapter skeleton in an empty project."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    playbook = get_playbook(body.playbook)
    if playbook is None:
        raise HTTPException(status_code=422, detail=f"Unknown playbook: {body.playbook}")
    if project.chapters:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This project already has chapters — the guide never overwrites your work.",
        )
    chapters = []
    for number, title, prompts in playbook.skeleton:
        blocks = [
            {
                "type": "paragraph",
                "runs": [{"text": f"[TO WRITE] {prompt}"}],
                "origin": "human",
            }
            for prompt in prompts
        ]
        # Round-trip through the canonical model so chapter and block ids are
        # minted ONCE and persisted. Storing id-less dicts means every later
        # validation invents fresh UUIDs — the id the structure tree shows
        # would never match the next request (chapter opens 404).
        chapter_doc = ChapterDoc.model_validate(
            {"number": number, "title": title, "blocks": blocks}
        )
        chapters.append(chapter_doc.model_dump(mode="json"))
    project.chapters = chapters
    meta = dict(project.meta or {})
    meta["guide_playbook"] = playbook.key
    project.meta = meta
    project.document_version += 1
    await db.commit()
    return {
        "playbook": playbook.key,
        "chapters_created": len(chapters),
        "document_version": project.document_version,
        "note": "Skeleton blocks are [TO WRITE] prompts — replace each with your own words.",
    }
