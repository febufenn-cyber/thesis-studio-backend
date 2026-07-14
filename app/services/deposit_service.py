"""Deposit orchestration (docs/LLD_MISSING_FEATURES.md MF3)."""

from __future__ import annotations

import os
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.deposit import DepositError, DepositMeta, DepositTarget
from app.models.deposit import Deposit
from app.models.export import Export
from app.models.project import Project
from app.services.export_service import MEDIA_TYPES
from app.services.storage_service import get_storage_service


def _meta_for(project: Project, orcid: str | None) -> DepositMeta:
    meta = project.meta or {}
    candidate = meta.get("candidate") or {}
    name = candidate.get("name") or "Unknown"
    return DepositMeta(
        title=meta.get("title") or project.title or "Untitled",
        creators=[name],
        description=f"Deposited from Acadensia project {project.id}.",
        orcid=orcid,
    )


async def create_deposit(
    db: AsyncSession,
    project: Project,
    export: Export,
    user_id: UUID,
    target: DepositTarget,
    *,
    orcid: str | None = None,
    sandbox: bool = True,
) -> Deposit:
    """Run the deposit state machine; persist status transitions and the DOI."""
    if export.status != "ready" or not export.storage_key:
        raise ValueError("Export is not ready for deposit.")

    deposit = Deposit(
        export_id=export.id, project_id=project.id, user_id=user_id,
        target=target.name, status="pending", orcid=orcid, sandbox=sandbox,
    )
    db.add(deposit)
    await db.flush()

    try:
        draft = await target.create_draft(_meta_for(project, orcid))
        deposit.remote_id = draft.remote_id
        deposit.status = "draft_created"
        await db.flush()

        path = await get_storage_service().download_to_temp(export.storage_key)
        try:
            filename = f"{project.id}.{export.format}"
            media = MEDIA_TYPES.get(export.format, "application/octet-stream")
            await target.upload_file(draft.remote_id, path, filename, media)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        deposit.status = "files_uploaded"
        await db.flush()

        published = await target.publish(draft.remote_id)
        deposit.doi = published.doi
        deposit.landing_url = published.landing_url
        deposit.response = published.raw
        deposit.status = "published"
        await db.flush()
    except DepositError as exc:
        deposit.status = "failed"
        deposit.error_message = str(exc)
        await db.flush()
    return deposit
