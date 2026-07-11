"""Human resolution endpoints for ambiguous citation occurrences."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.canonical.model import BlockQuoteBlock, ThesisDocument, VerseQuoteBlock
from app.db.deps import get_db
from app.ingest.citations import scan_document
from app.models.citation_resolution import CitationResolution
from app.models.event import Event
from app.models.manuscript_revision import ManuscriptRevision
from app.models.quote import Quote
from app.models.source import Source


router = APIRouter(tags=["phase1"])


class CitationResolutionRequest(BaseModel):
    block_id: UUID
    raw_citation: str = Field(..., min_length=2, max_length=300)
    source_id: UUID
    expected_version: int = Field(..., ge=1)
    page_or_loc: str | None = Field(None, max_length=100)


class CitationResolutionResponse(BaseModel):
    id: UUID
    block_id: UUID
    raw_citation: str
    source_id: UUID
    quote_id: UUID | None
    document_version: int


def _find_block(document: ThesisDocument, block_id: UUID):
    for chapter in document.chapters:
        for block in chapter.blocks:
            if block.id == block_id:
                return block
    for entry in document.front_matter:
        for block in entry.body_blocks:
            if block.id == block_id:
                return block
    return None


def _mark_import_issue_resolved(
    revision: ManuscriptRevision | None,
    block_id: UUID,
    raw_citation: str,
    source_id: UUID,
    user_id: UUID,
) -> None:
    if revision is None or not revision.import_report:
        return
    report = dict(revision.import_report)
    issues = [dict(issue) for issue in report.get("issues", [])]
    changed = False
    for issue in issues:
        evidence = issue.get("evidence") or {}
        if (
            issue.get("code") == "citation_resolution_required"
            and evidence.get("block_id") == str(block_id)
            and evidence.get("raw") == raw_citation
        ):
            issue["status"] = "resolved"
            issue["resolution"] = {
                "source_id": str(source_id),
                "resolved_by": str(user_id),
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            }
            changed = True
    if changed:
        report["issues"] = issues
        report.setdefault("summary", {})["issues_open"] = sum(
            1 for issue in issues if issue.get("status") != "resolved"
        )
        report["summary"]["issues_blocking"] = sum(
            1
            for issue in issues
            if issue.get("status") != "resolved" and issue.get("severity") == "block"
        )
        revision.import_report = report


@router.get("/projects/{project_id}/citation-resolutions")
async def list_citation_resolutions(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await fetch_owned_project(db, project_id, current_user.id)
    rows = list(
        (
            await db.execute(
                select(CitationResolution)
                .where(
                    CitationResolution.project_id == project_id,
                    CitationResolution.user_id == current_user.id,
                )
                .order_by(CitationResolution.created_at.asc())
            )
        ).scalars()
    )
    return [
        {
            "id": str(row.id),
            "revision_id": str(row.revision_id) if row.revision_id else None,
            "block_id": str(row.block_id),
            "raw_citation": row.raw_citation,
            "source_id": str(row.source_id),
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post(
    "/projects/{project_id}/citation-resolutions",
    response_model=CitationResolutionResponse,
)
async def resolve_citation_occurrence(
    project_id: UUID,
    body: CitationResolutionRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CitationResolutionResponse:
    project = await fetch_owned_project(db, project_id, current_user.id)
    if project.document_version != body.expected_version:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Project changed in another session. Reload before resolving.",
                "expected_version": body.expected_version,
                "current_version": project.document_version,
            },
        )
    source = (
        await db.execute(
            select(Source).where(
                Source.id == body.source_id,
                Source.project_id == project.id,
                Source.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    document = ThesisDocument.model_validate(
        {
            "meta": project.meta or {},
            "front_matter": project.front_matter or [],
            "chapters": project.chapters or [],
            "works_cited": project.works_cited or [],
        }
    )
    occurrence = next(
        (
            citation
            for citation in scan_document(document)
            if citation.block_id == str(body.block_id)
            and citation.raw == body.raw_citation
        ),
        None,
    )
    if occurrence is None:
        raise HTTPException(
            status_code=409,
            detail="The citation occurrence no longer exists in that block.",
        )

    resolution = (
        await db.execute(
            select(CitationResolution).where(
                CitationResolution.project_id == project.id,
                CitationResolution.block_id == body.block_id,
                CitationResolution.raw_citation == body.raw_citation,
            )
        )
    ).scalar_one_or_none()
    if resolution is None:
        resolution = CitationResolution(
            project_id=project.id,
            revision_id=project.active_revision_id,
            block_id=body.block_id,
            raw_citation=body.raw_citation,
            source_id=source.id,
            user_id=current_user.id,
        )
        db.add(resolution)
    else:
        resolution.source_id = source.id
        resolution.user_id = current_user.id
        resolution.revision_id = project.active_revision_id

    quote_id: UUID | None = None
    block = _find_block(document, body.block_id)
    if isinstance(block, (BlockQuoteBlock, VerseQuoteBlock)):
        quote_text = block.text if isinstance(block, BlockQuoteBlock) else "\n".join(block.lines)
        quote = None
        if block.quote_id:
            quote = (
                await db.execute(
                    select(Quote).where(
                        Quote.id == block.quote_id,
                        Quote.project_id == project.id,
                        Quote.user_id == current_user.id,
                    )
                )
            ).scalar_one_or_none()
        if quote is None:
            quote = Quote(
                source_id=source.id,
                project_id=project.id,
                user_id=current_user.id,
                page_or_loc=body.page_or_loc or occurrence.pages,
                text=quote_text,
                method="extracted",
                import_revision_id=project.active_revision_id,
                source_paragraph_index=block.source_paragraph_index,
                evidence_snapshot={
                    "raw_citation": body.raw_citation,
                    "block_id": str(block.id),
                    "revision_id": str(project.active_revision_id) if project.active_revision_id else None,
                },
                verified=False,
            )
            db.add(quote)
            await db.flush()
            block.quote_id = quote.id
        else:
            quote.source_id = source.id
            quote.page_or_loc = body.page_or_loc or occurrence.pages or quote.page_or_loc
            quote.verified = False
            quote.verified_at = None
            quote.verified_by = None
        quote_id = quote.id
        project.chapters = document.model_dump(mode="json")["chapters"]

    revision = None
    if project.active_revision_id:
        revision = (
            await db.execute(
                select(ManuscriptRevision).where(
                    ManuscriptRevision.id == project.active_revision_id,
                    ManuscriptRevision.project_id == project.id,
                    ManuscriptRevision.user_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
    _mark_import_issue_resolved(
        revision,
        body.block_id,
        body.raw_citation,
        source.id,
        current_user.id,
    )

    project.document_version += 1
    db.add(
        Event(
            project_id=project.id,
            user_id=current_user.id,
            kind="citation_resolved",
            data={
                "block_id": str(body.block_id),
                "raw_citation": body.raw_citation,
                "source_id": str(source.id),
                "quote_id": str(quote_id) if quote_id else None,
                "document_version": project.document_version,
            },
        )
    )
    await db.commit()
    await db.refresh(resolution)
    return CitationResolutionResponse(
        id=resolution.id,
        block_id=resolution.block_id,
        raw_citation=resolution.raw_citation,
        source_id=resolution.source_id,
        quote_id=quote_id,
        document_version=project.document_version,
    )
