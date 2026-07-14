"""Recipient-bound downloads for sealed external-review packages.

Tokens remain in a POST body, never a predictable URL path or query string. The
endpoint exposes only an export explicitly captured in the immutable package.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.deps import get_db
from app.models.export import Export
from app.models.institutional_governance import ExternalReviewGrant, SubmissionPackage
from app.services.export_service import MEDIA_TYPES
from app.services.storage_service import get_storage_service


router = APIRouter(tags=["submissions"])


class ExternalDownloadRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)
    recipient_email: str = Field(..., min_length=3, max_length=255)
    format: Literal["docx", "pdf"]


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@router.post("/external-review/download")
@limiter.limit(get_settings().RATE_LIMIT_DOWNLOAD)
async def download_external_review(
    request: Request,
    body: ExternalDownloadRequest,
    db: AsyncSession = Depends(get_db),
) -> Response:
    now = datetime.now(timezone.utc)
    grant = (
        await db.execute(
            select(ExternalReviewGrant).where(
                ExternalReviewGrant.token_hash == _token_hash(body.token),
                ExternalReviewGrant.status == "active",
                ExternalReviewGrant.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if grant is None or not secrets.compare_digest(
        body.recipient_email.strip().lower(), grant.recipient_email
    ):
        raise HTTPException(status_code=404, detail="External review download not found")
    if not grant.download_allowed or "sealed.download" not in set(grant.permissions or []):
        raise HTTPException(status_code=404, detail="External review download not found")

    package = (
        await db.execute(
            select(SubmissionPackage).where(
                SubmissionPackage.id == grant.submission_package_id,
                SubmissionPackage.state == "sealed",
            )
        )
    ).scalar_one_or_none()
    if package is None:
        raise HTTPException(status_code=404, detail="External review download not found")

    allowed_ids = {str(value) for value in package.export_ids or []}
    exports = list(
        (
            await db.execute(
                select(Export).where(
                    Export.project_id == package.project_id,
                    Export.document_version == package.document_version,
                    Export.format == body.format,
                    Export.status == "ready",
                )
            )
        ).scalars()
    )
    export = next(
        (
            row
            for row in exports
            if str(row.id) in allowed_ids
            and row.storage_key
            and row.checksum
            and (row.manifest or {}).get("state") == "final"
        ),
        None,
    )
    if export is None:
        raise HTTPException(status_code=404, detail="External review download not found")

    grant.last_accessed_at = now
    grant.access_count += 1
    await db.commit()

    filename = f"sealed-thesis-package-{package.package_number}.{body.format}"
    storage = get_storage_service()
    url = await storage.presigned_download_url(
        export.storage_key,
        filename,
        expires_in=300,
    )
    if url:
        return RedirectResponse(url=url, status_code=303)
    try:
        local_path = await storage.open_local_path(export.storage_key)
    except (NotImplementedError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="External review download not found")
    return FileResponse(
        local_path,
        media_type=MEDIA_TYPES.get(body.format, "application/octet-stream"),
        filename=filename,
        headers={
            "Cache-Control": "private, no-store",
            "X-Robofox-Watermark": grant.watermark or "Sealed external review copy",
            "X-Robofox-Package-Checksum": package.package_checksum,
        },
    )
