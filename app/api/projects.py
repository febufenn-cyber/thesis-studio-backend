"""v2 project router — projects, document JSON, sources, quotes, exports.

Per-user isolation contract (same as v1): every query filters user_id;
cross-user access returns 404, never 403. Child resources (sources, quotes,
exports) are reached only through an owned project or a user_id-filtered
direct lookup.
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse as FileDownloadResponse
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.models.event import Event
from app.models.export import Export
from app.models.project import Project
from app.models.quote import Quote
from app.models.source import Source
from app.schemas.project import (
    ChaptersUpdate,
    ExportRequest,
    ExportResponse,
    FrontMatterUpdate,
    MetaUpdate,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectResponse,
    QuoteCreate,
    QuoteResponse,
    SourceCreate,
    SourceResponse,
    WorksCitedUpdate,
)
from app.services.export_service import EXPORT_FORMATS, MEDIA_TYPES, run_export
from app.services.storage_service import get_storage_service


router = APIRouter(tags=["projects"])


# ---------------------------------------------------------------------------
# Projects CRUD
# ---------------------------------------------------------------------------


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Create a v2 project (Mode B operator by default)."""
    project = Project(
        user_id=current_user.id,
        title=body.title,
        mode=body.mode,
        doc_type=body.doc_type,
        format_profile=body.format_profile,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[Project]:
    """List the caller's non-archived projects, newest first."""
    result = await db.execute(
        select(Project)
        .where(Project.user_id == current_user.id)
        .where(Project.archived.is_(False))
        .order_by(Project.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Full project detail including the document JSON columns."""
    return await fetch_owned_project(db, project_id, current_user.id)


@router.delete("/projects/{project_id}", status_code=204, response_class=Response)
async def archive_project(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Soft-delete (archive) a project."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    project.archived = True
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Document JSON updates (validated through the canonical model)
# ---------------------------------------------------------------------------


@router.patch("/projects/{project_id}/meta", response_model=ProjectDetailResponse)
async def update_meta(
    project_id: UUID,
    body: MetaUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Replace the ThesisMeta block."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    project.meta = body.meta.model_dump(mode="json")
    await db.commit()
    await db.refresh(project)
    return project


@router.patch("/projects/{project_id}/chapters", response_model=ProjectDetailResponse)
async def update_chapters(
    project_id: UUID,
    body: ChaptersUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Replace the chapters list (validated canonical ChapterDoc[])."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    project.chapters = [c.model_dump(mode="json") for c in body.chapters]
    await db.commit()
    await db.refresh(project)
    return project


@router.patch("/projects/{project_id}/front_matter", response_model=ProjectDetailResponse)
async def update_front_matter(
    project_id: UUID,
    body: FrontMatterUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Replace the front-matter entry list."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    project.front_matter = [e.model_dump(mode="json") for e in body.front_matter]
    await db.commit()
    await db.refresh(project)
    return project


@router.patch("/projects/{project_id}/works_cited", response_model=ProjectDetailResponse)
async def update_works_cited(
    project_id: UUID,
    body: WorksCitedUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Replace the works-cited source references."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    project.works_cited = [r.model_dump(mode="json") for r in body.works_cited]
    await db.commit()
    await db.refresh(project)
    return project


# ---------------------------------------------------------------------------
# Sources & quotes (the citation registry — the only path into Works Cited)
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/sources", response_model=SourceResponse, status_code=201
)
async def create_source(
    project_id: UUID,
    body: SourceCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Source:
    """Add a registry source to the project."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    source = Source(
        project_id=project.id,
        user_id=current_user.id,
        kind=body.kind,
        fields=body.fields,
        verified=body.verified,
        verify_note=body.verify_note,
        consulted_flag=body.consulted_flag,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


@router.get("/projects/{project_id}/sources", response_model=list[SourceResponse])
async def list_sources(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[Source]:
    """List the project's registry sources."""
    await fetch_owned_project(db, project_id, current_user.id)
    result = await db.execute(
        select(Source)
        .where(Source.project_id == project_id)
        .where(Source.user_id == current_user.id)
        .order_by(Source.created_at.asc())
    )
    return list(result.scalars().all())


@router.delete(
    "/projects/{project_id}/sources/{source_id}",
    status_code=204,
    response_class=Response,
)
async def delete_source(
    project_id: UUID,
    source_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove a source (and, via cascade, its quotes)."""
    await fetch_owned_project(db, project_id, current_user.id)
    result = await db.execute(
        select(Source)
        .where(Source.id == source_id)
        .where(Source.project_id == project_id)
        .where(Source.user_id == current_user.id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(source)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/sources/{source_id}/quotes",
    response_model=QuoteResponse,
    status_code=201,
)
async def create_quote(
    project_id: UUID,
    source_id: UUID,
    body: QuoteCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Quote:
    """Register a quotation against a source (registry rule: no other path)."""
    await fetch_owned_project(db, project_id, current_user.id)
    src = (
        await db.execute(
            select(Source)
            .where(Source.id == source_id)
            .where(Source.project_id == project_id)
            .where(Source.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=404, detail="Source not found")
    quote = Quote(
        source_id=source_id,
        project_id=project_id,
        user_id=current_user.id,
        page_or_loc=body.page_or_loc,
        text=body.text,
        verified=body.verified,
        method=body.method,
    )
    db.add(quote)
    await db.commit()
    await db.refresh(quote)
    return quote


@router.get("/projects/{project_id}/quotes", response_model=list[QuoteResponse])
async def list_quotes(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[Quote]:
    """List all registered quotes for the project."""
    await fetch_owned_project(db, project_id, current_user.id)
    result = await db.execute(
        select(Quote)
        .where(Quote.project_id == project_id)
        .where(Quote.user_id == current_user.id)
        .order_by(Quote.created_at.asc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Exports (Gate G4 + background render + download)
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/exports",
    response_model=list[ExportResponse],
    status_code=202,
)
async def trigger_exports(
    project_id: UUID,
    body: ExportRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[Export]:
    """Start background exports for the requested formats.

    Gate G4: `acknowledge` must be true (operator/student attests authorship
    responsibility). 409 when the project has no chapters or a requested
    format is already running.
    """
    project = await fetch_owned_project(db, project_id, current_user.id)

    if not body.acknowledge:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Export requires acknowledgment (Gate G4): the author attests"
                " responsibility for the document's claims."
            ),
        )
    if not project.chapters:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nothing to export — the project has no chapters yet.",
        )

    formats = list(EXPORT_FORMATS) if body.formats == "all" else list(body.formats)
    unknown = [f for f in formats if f not in EXPORT_FORMATS]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown export formats: {', '.join(unknown)}",
        )

    running = {
        row.format
        for row in (
            await db.execute(
                select(Export)
                .where(Export.project_id == project.id)
                .where(Export.status == "running")
            )
        ).scalars()
    }

    db.add(Event(
        project_id=project.id,
        user_id=current_user.id,
        kind="export_acknowledged",
        data={"formats": formats},
    ))

    created: list[Export] = []
    for fmt in formats:
        if fmt in running:
            continue
        export = Export(
            project_id=project.id,
            user_id=current_user.id,
            format=fmt,
            status="running",
        )
        db.add(export)
        created.append(export)
    await db.commit()
    for export in created:
        await db.refresh(export)
        background_tasks.add_task(run_export, export.id, project.id, current_user.id)

    if not created:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="All requested formats are already exporting.",
        )
    return created


@router.get("/projects/{project_id}/exports", response_model=list[ExportResponse])
async def list_exports(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[Export]:
    """List export jobs for the project, newest first."""
    await fetch_owned_project(db, project_id, current_user.id)
    result = await db.execute(
        select(Export)
        .where(Export.project_id == project_id)
        .where(Export.user_id == current_user.id)
        .order_by(Export.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/exports/{export_id}/download", response_model=None)
async def download_export(
    export_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse | FileDownloadResponse:
    """Download a ready export (presigned redirect or direct file bytes)."""
    export = (
        await db.execute(
            select(Export)
            .where(Export.id == export_id)
            .where(Export.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if export is None:
        raise HTTPException(status_code=404, detail="Export not found")
    if export.status != "ready":
        raise HTTPException(status_code=409, detail="Export is not ready.")

    project = await fetch_owned_project(db, export.project_id, current_user.id)
    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", project.title)[:60] or "Thesis"
    filename = f"{safe_title}.{export.format}"

    storage = get_storage_service()
    url = await storage.presigned_download_url(export.storage_key, filename)
    if url:
        return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    local_path = await storage.open_local_path(export.storage_key)
    return FileDownloadResponse(
        local_path,
        filename=filename,
        media_type=MEDIA_TYPES.get(export.format, "application/octet-stream"),
    )
