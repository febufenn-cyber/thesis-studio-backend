"""API-key management (docs/LLD_MISSING_FEATURES.md MF6).

Cookie-authenticated CRUD. The plaintext key is returned exactly once at
creation; only its SHA-256 hash is stored. Listing never reveals the key.
"""

from __future__ import annotations

import secrets
from uuid import UUID

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import API_KEY_PREFIX, CurrentUser, hash_api_key
from app.db.deps import get_db
from app.models.api_key import ApiKey

router = APIRouter(tags=["api-keys"])

_ALLOWED_SCOPES = {"read", "export", "resolve", "import"}


class ApiKeyCreateRequest(BaseModel):
    label: str = ""
    scopes: list[str] = []


def _key_dict(row: ApiKey) -> dict:
    return {
        "id": str(row.id),
        "prefix": row.prefix,
        "label": row.label,
        "scopes": row.scopes,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create an API key; the plaintext is returned once and never again."""
    bad = set(body.scopes) - _ALLOWED_SCOPES
    if bad:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown scopes: {sorted(bad)}",
        )
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    row = ApiKey(
        user_id=current_user.id,
        key_hash=hash_api_key(raw),
        prefix=raw[:12],
        scopes=body.scopes,
        label=body.label,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {**_key_dict(row), "key": raw}  # plaintext shown once


@router.get("/api-keys")
async def list_api_keys(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the caller's API keys (never the plaintext)."""
    rows = list(
        (
            await db.execute(
                select(ApiKey)
                .where(ApiKey.user_id == current_user.id)
                .order_by(ApiKey.created_at.desc())
            )
        ).scalars()
    )
    return {"api_keys": [_key_dict(r) for r in rows]}


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke an API key (immediate; idempotent)."""
    row = (
        await db.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": str(row.id), "revoked": True}
