"""Pydantic schemas for projects, manuscript revisions, registry and exports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.canonical.model import ChapterDoc, FrontMatterEntry, ThesisMeta, WorksCitedRef


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    mode: Literal["student", "operator"] = "operator"
    doc_type: str = "ma_dissertation"
    format_profile: str = "tn_university"


class ProjectResponse(BaseModel):
    id: UUID
    title: str
    mode: str
    doc_type: str
    status: str
    format_profile: str
    document_version: int
    active_revision_id: UUID | None
    archived: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectDetailResponse(ProjectResponse):
    meta: dict
    front_matter: list
    chapters: list
    works_cited: list


class VersionedMutation(BaseModel):
    """Optimistic concurrency token.

    Optional only for the legacy v2 JSON console during migration. The field is
    excluded from ``model_dump`` so it can never be mistaken for ORM content.
    """

    expected_version: int | None = Field(None, ge=1, exclude=True)


class MetaUpdate(VersionedMutation):
    meta: ThesisMeta


class ChaptersUpdate(VersionedMutation):
    chapters: list[ChapterDoc]


class FrontMatterUpdate(VersionedMutation):
    front_matter: list[FrontMatterEntry]


class WorksCitedUpdate(VersionedMutation):
    works_cited: list[WorksCitedRef]


class SourceCreate(VersionedMutation):
    kind: str
    fields: dict = Field(default_factory=dict)
    raw_entry: str | None = None
    parse_status: Literal["fully_structured", "structured_with_review", "preserved_raw"] = (
        "structured_with_review"
    )
    identifiers: dict = Field(default_factory=dict)
    verified: bool = False
    verify_note: str | None = None
    verification_method: str | None = None
    consulted_flag: bool = False


class SourceUpdate(VersionedMutation):
    kind: str | None = None
    fields: dict | None = None
    raw_entry: str | None = None
    parse_status: Literal["fully_structured", "structured_with_review", "preserved_raw"] | None = None
    identifiers: dict | None = None
    verified: bool | None = None
    verify_note: str | None = None
    verification_method: str | None = None
    consulted_flag: bool | None = None


class SourceResponse(BaseModel):
    id: UUID
    project_id: UUID
    kind: str
    fields: dict
    raw_entry: str | None
    parse_status: str
    source_paragraph_index: int | None
    import_revision_id: UUID | None
    parser_confidence: float | None
    parser_version: str | None
    identifiers: dict
    verified: bool
    verify_note: str | None
    verified_at: datetime | None
    verified_by: UUID | None
    verification_method: str | None
    consulted_flag: bool
    created_at: datetime

    class Config:
        from_attributes = True


class QuoteCreate(VersionedMutation):
    page_or_loc: str = Field("", max_length=100)
    text: str = Field(..., min_length=1)
    verified: bool = False
    method: Literal["pasted", "extracted", "web_retrieved"] = "pasted"
    verification_method: str | None = None
    evidence_snapshot: dict = Field(default_factory=dict)


class QuoteResponse(BaseModel):
    id: UUID
    source_id: UUID
    project_id: UUID
    page_or_loc: str
    text: str
    verified: bool
    method: str
    import_revision_id: UUID | None
    source_paragraph_index: int | None
    evidence_snapshot: dict
    verified_at: datetime | None
    verified_by: UUID | None
    verification_method: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ManuscriptRevisionResponse(BaseModel):
    id: UUID
    project_id: UUID
    revision_number: int
    supersedes_revision_id: UUID | None
    original_filename: str
    mime_type: str
    size_bytes: int
    checksum: str
    parser_version: str
    canonical_schema_version: int
    import_report: dict | None
    status: str
    error_message: str | None
    applied: bool
    applied_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class ManuscriptUploadResponse(BaseModel):
    revision: ManuscriptRevisionResponse
    job_id: UUID
    duplicate_of_revision_id: UUID | None = None


class RevisionApplyRequest(BaseModel):
    expected_version: int = Field(..., ge=1)


class VerificationResponse(BaseModel):
    document_version: int
    manuscript_revision_id: UUID | None
    passed: bool
    report: dict


class ExportRequest(VersionedMutation):
    formats: list[str] | Literal["all"] = "all"
    acknowledge: bool = False
    allow_review_export: bool = False


class ExportResponse(BaseModel):
    id: UUID
    format: str
    status: str
    document_version: int
    manuscript_revision_id: UUID | None
    profile_version: str
    error_message: str | None
    size_bytes: int | None
    report: dict | None
    manifest: dict | None
    created_at: datetime

    class Config:
        from_attributes = True


class JobResponse(BaseModel):
    id: UUID
    kind: str
    project_id: UUID | None
    status: str
    attempts: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
