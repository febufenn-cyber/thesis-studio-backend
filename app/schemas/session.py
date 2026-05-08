"""Pydantic schemas for sessions and messages."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ---- Session schemas ----

class SessionCreate(BaseModel):
    """POST /sessions body."""

    title: str | None = Field(None, max_length=300)


class SessionUpdate(BaseModel):
    """PATCH /sessions/{id} body. All fields optional."""

    title: str | None = Field(None, max_length=300)
    primary_text: str | None = Field(None, max_length=500)
    subfield: str | None = Field(None, max_length=100)
    framework: str | None = Field(None, max_length=200)
    thesis_statement: str | None = None
    supervisor_full_name: str | None = Field(None, max_length=200)
    supervisor_designation: str | None = Field(None, max_length=200)
    hod_full_name: str | None = Field(None, max_length=200)
    study_period: str | None = Field(None, max_length=100)


class SessionResponse(BaseModel):
    """Single session in list and detail endpoints."""

    id: UUID
    title: str
    phase: str
    primary_text: str | None
    subfield: str | None
    framework: str | None
    thesis_statement: str | None
    supervisor_full_name: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---- Message schemas ----

class MessageCreate(BaseModel):
    """POST /sessions/{id}/messages body."""

    content: str = Field(..., min_length=1, max_length=20_000)


class MessageResponse(BaseModel):
    """A single message in the session history endpoint."""

    id: UUID
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True
