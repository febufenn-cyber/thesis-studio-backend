"""API contracts for the Phase 2 review and editing workspace."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CommandRequest(BaseModel):
    command_type: str = Field(..., min_length=1, max_length=60)
    payload: dict = Field(default_factory=dict)
    expected_document_version: int = Field(..., ge=1)
    client_request_id: str | None = Field(None, max_length=120)
    batch_id: UUID | None = None
    summary: str | None = Field(None, max_length=400)


class CommandRecord(BaseModel):
    id: UUID
    command_type: str
    summary: str
    target_type: str | None
    target_id: UUID | None
    batch_id: UUID | None
    document_version_before: int
    document_version_after: int
    replays_command_id: UUID | None
    created_at: datetime

    class Config:
        from_attributes = True


class CommandResultResponse(BaseModel):
    command: CommandRecord
    document_version: int
    changed_block_ids: list[UUID]
    changed_chapter_ids: list[UUID]
    invalidations: dict


class UndoRedoRequest(BaseModel):
    expected_document_version: int = Field(..., ge=1)


class SnapshotCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=180)
    expected_document_version: int = Field(..., ge=1)


class SnapshotRestoreRequest(BaseModel):
    expected_document_version: int = Field(..., ge=1)


class SnapshotResponse(BaseModel):
    id: UUID
    name: str
    reason: str
    automatic: bool
    document_version: int
    manuscript_revision_id: UUID | None
    checksum: str
    created_at: datetime

    class Config:
        from_attributes = True


class ReviewItemResponse(BaseModel):
    id: UUID
    revision_id: UUID | None
    block_id: UUID | None
    source_id: UUID | None
    quote_id: UUID | None
    category: str
    rule: str
    severity: str
    title: str
    explanation: str
    why_it_matters: str
    location: dict
    recommended_actions: list
    evidence: dict
    status: str
    first_seen_version: int
    last_seen_version: int
    resolution_note: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReviewResolveRequest(BaseModel):
    action: Literal["resolve", "acknowledge", "reopen"]
    note: str = Field(..., min_length=1, max_length=2000)
    expected_document_version: int = Field(..., ge=1)


class PreviewRequest(BaseModel):
    expected_document_version: int = Field(..., ge=1)
    force: bool = False


class PreviewResponse(BaseModel):
    id: UUID
    document_version: int
    manuscript_revision_id: UUID | None
    profile_version: str
    status: str
    checksum: str | None
    size_bytes: int | None
    page_count: int | None
    error_message: str | None
    manifest: dict
    stale: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SearchResult(BaseModel):
    kind: str
    id: UUID
    chapter_id: UUID | None = None
    chapter_number: int | None = None
    block_type: str | None = None
    status: str | None = None
    title: str = ""
    snippet: str = ""
    source_paragraph_index: int | None = None


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResult]
