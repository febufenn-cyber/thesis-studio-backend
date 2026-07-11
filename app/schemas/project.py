"""Pydantic schemas for v2 projects, sources, quotes, and exports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.canonical.model import (
    ChapterDoc,
    FrontMatterEntry,
    ThesisMeta,
    WorksCitedRef,
)


# ---------------------------------------------------------------------------
# Project schemas
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    """POST /projects body."""

    title: str = Field(..., min_length=1, max_length=300)
    mode: Literal["student", "operator"] = "operator"
    doc_type: str = Field(
        "ma_dissertation",
        description=(
            "ma_dissertation | mphil_dissertation | phd_thesis"
            " | project_report | research_paper"
        ),
    )
    format_profile: str = Field(
        "tn_university",
        description="tn_university | mla_strict",
    )


class ProjectResponse(BaseModel):
    """Summary view returned by list and create endpoints."""

    id: UUID
    title: str
    mode: str
    doc_type: str
    status: str
    format_profile: str
    archived: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectDetailResponse(ProjectResponse):
    """Full view returned by the single-project GET endpoint.

    ``meta``, ``front_matter``, ``chapters``, and ``works_cited`` are the raw
    JSONB values; callers may pass them to ThesisMeta.model_validate() etc.
    """

    meta: dict
    front_matter: list
    chapters: list
    works_cited: list


class MetaUpdate(BaseModel):
    """PATCH /projects/{id}/meta body — replaces the full ThesisMeta block.

    Validated against ThesisMeta so callers know the shape is correct before
    it is serialised to JSONB.
    """

    meta: ThesisMeta


class ChaptersUpdate(BaseModel):
    """PATCH /projects/{id}/chapters body — replaces the full chapters list."""

    chapters: list[ChapterDoc]


class FrontMatterUpdate(BaseModel):
    """PATCH /projects/{id}/front_matter body."""

    front_matter: list[FrontMatterEntry]


class WorksCitedUpdate(BaseModel):
    """PATCH /projects/{id}/works_cited body."""

    works_cited: list[WorksCitedRef]


# ---------------------------------------------------------------------------
# Source schemas
# ---------------------------------------------------------------------------


class SourceCreate(BaseModel):
    """POST /projects/{id}/sources body."""

    kind: str = Field(
        ...,
        description=(
            "book | translated_book | chapter_in_collection"
            " | journal | journal_db | web | film"
        ),
    )
    fields: dict = Field(default_factory=dict, description="Kind-specific bibliographic fields.")
    verified: bool = False
    verify_note: str | None = None
    consulted_flag: bool = False


class SourceResponse(BaseModel):
    """Single source returned by the API."""

    id: UUID
    project_id: UUID
    kind: str
    fields: dict
    verified: bool
    verify_note: str | None
    consulted_flag: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Quote schemas
# ---------------------------------------------------------------------------


class QuoteCreate(BaseModel):
    """POST /projects/{id}/sources/{source_id}/quotes body."""

    page_or_loc: str = Field("", max_length=50)
    text: str = Field(..., min_length=1)
    verified: bool = False
    method: Literal["pasted", "extracted", "web_retrieved"] = "pasted"


class QuoteResponse(BaseModel):
    """Single quote returned by the API."""

    id: UUID
    source_id: UUID
    project_id: UUID
    page_or_loc: str
    text: str
    verified: bool
    method: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Export schemas
# ---------------------------------------------------------------------------


class ExportRequest(BaseModel):
    """POST /projects/{id}/exports body.

    ``formats`` is a list of format strings or the literal ``"all"``.
    ``acknowledge`` must be True for the G4 gate to pass (student has read and
    accepts authorship responsibility).
    """

    formats: list[str] | Literal["all"] = Field(
        "all",
        description='List of formats (docx, pdf, md, txt) or "all".',
    )
    acknowledge: bool = Field(
        False,
        description=(
            "Must be True to pass Gate G4: student attests authorship"
            " responsibility and AI-disclosure compliance."
        ),
    )


class ExportResponse(BaseModel):
    """Single export job returned by the API."""

    id: UUID
    format: str
    status: str
    error_message: str | None
    size_bytes: int | None
    created_at: datetime

    class Config:
        from_attributes = True
