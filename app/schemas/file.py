"""Pydantic response schemas for file-related endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CompileTriggerResponse(BaseModel):
    """Response body for POST /sessions/{id}/compile (202 Accepted)."""

    file_id: UUID
    filename: str
    status: str


class FileResponse(BaseModel):
    """A single compiled file entry, returned by the files list endpoint."""

    id: UUID
    filename: str
    status: str
    error_message: str | None
    size_bytes: int | None
    created_at: datetime

    class Config:
        from_attributes = True
