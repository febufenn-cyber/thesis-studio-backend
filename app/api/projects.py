"""Project, canonical document, registry and export API.

All resources are isolated by user_id. The trusted UI sends optimistic
concurrency tokens for every mutation; missing tokens remain temporarily
accepted only for the legacy v2 JSON console.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse as FileDownloadResponse
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.canonical.model import ThesisMeta
from app.db.deps import get_db
from app.domains.profiles import UnknownDomainProfile, get_domain_profile
from app.renderers.bibtex import to_bibtex
from app.models.event import Event
from app.models.export import Export
from app.models.project import Project
from app.models.quote import Quote
from app.models.institution import Institution
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
from app.services.export_service import EXPORT_FORMATS, MEDIA_TYPES
from app.services.job_queue import enqueue_job
from app.services.storage_service import get_storage_service
from app.services.verification_service import verify_project


router = APIRouter(tags=["projects"])


def _assert_version(project: Project, expected: int | None) -> None:
    """Reject stale writes; tolerate omitted tokens only during legacy migration."""

    if expected is None:
        return
    if project.document_version != expected:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Project changed in another session. Reload before saving.",
                "expected_version": expected,
                "current_version": project.document_version,
            },
        )


async def _commit_canonical(project: Project, db: AsyncSession) -> Project:
    project.document_version += 1
    await db.commit()
    await db.refresh(project)
    return project


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = Project(
        user_id=current_user.id,
        title=body.title,
        mode=body.mode,
        doc_type=body.doc_type,
        format_profile=body.format_profile,
        document_version=1,
    )
    if body.domain_profile is not None:
        try:
            profile = get_domain_profile(body.domain_profile)
        except UnknownDomainProfile:
            raise HTTPException(status_code=422, detail="Unknown domain profile")
        meta = ThesisMeta()
        meta.citation_style = profile.default_citation_style
        meta.domain_profile = profile.key
        project.meta = meta.model_dump(mode="json")
    # FRICTION_LOG F4: the submission-metadata title gates readiness but lived
    # empty while the project title sat on screen — two invisible "titles".
    # Default it from the project title; the student can refine it later.
    meta_dict = dict(project.meta or {})
    if not (meta_dict.get("title") or "").strip():
        meta_dict["title"] = body.title.strip()
    # Title-page slots default from the student's real institution (never
    # invented): college name/affiliation/city and department. Editable later.
    inst = (
        await db.execute(
            select(Institution).where(Institution.id == current_user.institution_id)
        )
    ).scalar_one_or_none()
    if inst is not None:
        college = dict(meta_dict.get("college") or {})
        if not (college.get("name") or "").strip():
            college["name"] = inst.name
        if not (college.get("affiliation") or "").strip() and inst.university_name:
            college["affiliation"] = inst.university_name
        if not (college.get("city") or "").strip() and inst.short_address:
            college["city"] = inst.short_address
        meta_dict["college"] = college
        if not (meta_dict.get("department") or "").strip() and inst.default_department:
            meta_dict["department"] = inst.default_department
    project.meta = meta_dict
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Project]:
    return list(
        (
            await db.execute(
                select(Project)
                .where(Project.user_id == current_user.id, Project.archived.is_(False))
                .order_by(Project.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    return await fetch_owned_project(db, project_id, current_user.id)


@router.delete("/projects/{project_id}", status_code=204, response_class=Response)
async def archive_project(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    project = await fetch_owned_project(db, project_id, current_user.id)
    project.archived = True
    await db.commit()
    return Response(status_code=204)


@router.patch("/projects/{project_id}/meta", response_model=ProjectDetailResponse)
async def update_meta(
    project_id: UUID,
    body: MetaUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project, body.expected_version)
    project.meta = body.meta.model_dump(mode="json")
    return await _commit_canonical(project, db)


@router.patch("/projects/{project_id}/chapters", response_model=ProjectDetailResponse)
async def update_chapters(
    project_id: UUID,
    body: ChaptersUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project, body.expected_version)
    project.chapters = [chapter.model_dump(mode="json") for chapter in body.chapters]
    return await _commit_canonical(project, db)


@router.patch("/projects/{project_id}/front_matter", response_model=ProjectDetailResponse)
async def update_front_matter(
    project_id: UUID,
    body: FrontMatterUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project, body.expected_version)
    project.front_matter = [entry.model_dump(mode="json") for entry in body.front_matter]
    return await _commit_canonical(project, db)


@router.patch("/projects/{project_id}/works_cited", response_model=ProjectDetailResponse)
async def update_works_cited(
    project_id: UUID,
    body: WorksCitedUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project, body.expected_version)
    project.works_cited = [reference.model_dump(mode="json") for reference in body.works_cited]
    return await _commit_canonical(project, db)


@router.post("/projects/{project_id}/sources", response_model=SourceResponse, status_code=201)
async def create_source(
    project_id: UUID,
    body: SourceCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Source:
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project, body.expected_version)
    now = datetime.now(timezone.utc) if body.verified else None
    source = Source(
        project_id=project.id,
        user_id=current_user.id,
        kind=body.kind,
        fields=body.fields,
        raw_entry=body.raw_entry,
        parse_status=body.parse_status,
        identifiers=body.identifiers,
        verified=body.verified,
        verify_note=body.verify_note,
        verified_at=now,
        verified_by=current_user.id if body.verified else None,
        verification_method=body.verification_method or ("manual" if body.verified else None),
        consulted_flag=body.consulted_flag,
    )
    db.add(source)
    project.document_version += 1
    await db.commit()
    await db.refresh(source)
    return source


@router.get("/projects/{project_id}/sources", response_model=list[SourceResponse])
async def list_sources(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[Source]:
    await fetch_owned_project(db, project_id, current_user.id)
    return list(
        (
            await db.execute(
                select(Source)
                .where(Source.project_id == project_id, Source.user_id == current_user.id)
                .order_by(Source.created_at.asc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )


@router.get("/projects/{project_id}/references.bib", response_class=PlainTextResponse)
async def export_references_bibtex(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    """Export the project's citation registry as a BibTeX (.bib) document."""
    await fetch_owned_project(db, project_id, current_user.id)
    sources = list(
        (
            await db.execute(
                select(Source)
                .where(Source.project_id == project_id, Source.user_id == current_user.id)
                .order_by(Source.created_at.asc())
            )
        ).scalars()
    )
    return PlainTextResponse(to_bibtex(sources), media_type="application/x-bibtex")


@router.delete(
    "/projects/{project_id}/sources/{source_id}",
    status_code=204,
    response_class=Response,
)
async def delete_source(
    project_id: UUID,
    source_id: UUID,
    current_user: CurrentUser,
    expected_version: int | None = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> Response:
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project, expected_version)
    source = (
        await db.execute(
            select(Source).where(
                Source.id == source_id,
                Source.project_id == project_id,
                Source.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(source)
    project.document_version += 1
    await db.commit()
    return Response(status_code=204)


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
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project, body.expected_version)
    source = (
        await db.execute(
            select(Source).where(
                Source.id == source_id,
                Source.project_id == project_id,
                Source.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    quote = Quote(
        source_id=source_id,
        project_id=project_id,
        user_id=current_user.id,
        page_or_loc=body.page_or_loc,
        text=body.text,
        verified=body.verified,
        method=body.method,
        evidence_snapshot=body.evidence_snapshot,
        verified_at=datetime.now(timezone.utc) if body.verified else None,
        verified_by=current_user.id if body.verified else None,
        verification_method=body.verification_method or ("manual" if body.verified else None),
    )
    db.add(quote)
    project.document_version += 1
    await db.commit()
    await db.refresh(quote)
    return quote


@router.get("/projects/{project_id}/quotes", response_model=list[QuoteResponse])
async def list_quotes(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[Quote]:
    await fetch_owned_project(db, project_id, current_user.id)
    return list(
        (
            await db.execute(
                select(Quote)
                .where(Quote.project_id == project_id, Quote.user_id == current_user.id)
                .order_by(Quote.created_at.asc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )


@router.post(
    "/projects/{project_id}/exports",
    response_model=list[ExportResponse],
    status_code=202,
)
async def trigger_exports(
    project_id: UUID,
    body: ExportRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[Export]:
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project, body.expected_version)
    if not body.acknowledge:
        raise HTTPException(
            status_code=409,
            detail="Export requires authorship and citation responsibility acknowledgment.",
        )

    formats = list(EXPORT_FORMATS) if body.formats == "all" else list(dict.fromkeys(body.formats))
    unknown = [fmt for fmt in formats if fmt not in EXPORT_FORMATS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown export formats: {', '.join(unknown)}")

    verification = await verify_project(db, project)
    if not verification["pass"] and not body.allow_review_export:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Final export is blocked until verification issues are resolved.",
                "verification": verification,
            },
        )

    active = {
        row.format
        for row in (
            await db.execute(
                select(Export).where(
                    Export.project_id == project.id,
                    Export.status.in_(("queued", "running")),
                )
            )
        ).scalars()
    }
    created: list[Export] = []
    for fmt in formats:
        if fmt in active:
            continue
        export = Export(
            project_id=project.id,
            user_id=current_user.id,
            format=fmt,
            status="queued",
            document_version=project.document_version,
            manuscript_revision_id=project.active_revision_id,
            profile_version=verification.get("profile_version", f"builtin:{project.format_profile}"),
            report=verification,
            manifest={
                "state": "final" if verification["pass"] else "review",
                "project_id": str(project.id),
                "document_version": project.document_version,
                "manuscript_revision_id": str(project.active_revision_id) if project.active_revision_id else None,
                "format_profile": project.format_profile,
                "format_profile_version": verification.get("profile_version"),
                "verification_counts": verification["counts"],
                "authorship_acknowledged": True,
            },
        )
        db.add(export)
        await db.flush()
        await enqueue_job(
            db,
            kind="export",
            user_id=current_user.id,
            project_id=project.id,
            payload={
                "export_id": str(export.id),
                "project_id": str(project.id),
                "user_id": str(current_user.id),
            },
        )
        created.append(export)

    if not created:
        raise HTTPException(status_code=409, detail="All requested formats are already queued or running.")
    db.add(
        Event(
            project_id=project.id,
            user_id=current_user.id,
            kind="export_acknowledged",
            data={
                "formats": formats,
                "document_version": project.document_version,
                "review_export": not verification["pass"],
            },
        )
    )
    await db.commit()
    for export in created:
        await db.refresh(export)
    return created


@router.get("/projects/{project_id}/exports", response_model=list[ExportResponse])
async def list_exports(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Export]:
    await fetch_owned_project(db, project_id, current_user.id)
    return list(
        (
            await db.execute(
                select(Export)
                .where(Export.project_id == project_id, Export.user_id == current_user.id)
                .order_by(Export.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )


@router.get("/exports/{export_id}/manifest")
async def export_manifest(
    export_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    export = (
        await db.execute(
            select(Export).where(Export.id == export_id, Export.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if export is None:
        raise HTTPException(status_code=404, detail="Export not found")
    return {
        "export_id": str(export.id),
        "status": export.status,
        "checksum": export.checksum,
        "report": export.report,
        "manifest": export.manifest,
    }


@router.get("/exports/{export_id}/download", response_model=None)
async def download_export(
    export_id: UUID,
    current_user: CurrentUser,
    allow_stale: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    export = (
        await db.execute(
            select(Export).where(Export.id == export_id, Export.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if export is None:
        raise HTTPException(status_code=404, detail="Export not found")
    if export.status != "ready":
        raise HTTPException(status_code=409, detail="Export is not ready.")
    project = await fetch_owned_project(db, export.project_id, current_user.id)
    stale = export.document_version != project.document_version
    if stale and not allow_stale:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This export is stale because the project changed.",
                "export_document_version": export.document_version,
                "current_document_version": project.document_version,
                "download_with_allow_stale": True,
            },
        )

    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", project.title)[:60] or "Thesis"
    state = (export.manifest or {}).get("state")
    prefix = "REVIEW_" if state == "review" else ("STALE_" if stale else "")
    filename = f"{prefix}{safe_title}.{export.format}"
    storage = get_storage_service()
    url = await storage.presigned_download_url(export.storage_key, filename)
    if url:
        return RedirectResponse(url, status_code=307)
    return FileDownloadResponse(
        await storage.open_local_path(export.storage_key),
        filename=filename,
        media_type=MEDIA_TYPES.get(export.format, "application/octet-stream"),
    )
