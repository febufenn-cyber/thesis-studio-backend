"""Measurable reliability and security-programme control plane."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentApplicationSession, CurrentUser
from app.collaboration.capabilities import require_institution_capability
from app.commercial.sessions import require_recent_reauthentication
from app.db.deps import get_db
from app.models.commercial import (
    SecurityRequirementEvidence,
    SLIMeasurement,
    SLODefinition,
)
from app.models.job import Job


router = APIRouter(tags=["commercial-reliability"])


class SLOCreate(BaseModel):
    component_key: str = Field(..., min_length=2, max_length=60)
    indicator: str = Field(..., min_length=2, max_length=100)
    objective: Decimal = Field(..., ge=0)
    comparison: str = Field(..., pattern=r"^(gte|lte|eq)$")
    unit: str = Field(..., min_length=1, max_length=30)
    window_days: int = Field(30, ge=1, le=365)
    external_commitment: bool = False


class SLIMeasurementCreate(BaseModel):
    slo_id: UUID
    value: Decimal
    numerator: Decimal | None = None
    denominator: Decimal | None = None
    window_start: datetime
    window_end: datetime
    dimensions: dict = Field(default_factory=dict)
    source: str = Field(..., min_length=2, max_length=100)


class SecurityEvidenceCreate(BaseModel):
    standard: str = Field("OWASP ASVS", min_length=2, max_length=60)
    version: str = Field("5.0", min_length=1, max_length=30)
    level: str | None = Field(None, max_length=30)
    requirement_id: str = Field(..., min_length=2, max_length=80)
    requirement_text: str = Field(..., min_length=10, max_length=10000)
    implementation: str = Field(..., min_length=10, max_length=20000)
    automated_test_reference: str | None = Field(None, max_length=500)
    manual_evidence_reference: str | None = Field(None, max_length=500)
    owner: str = Field(..., min_length=2, max_length=200)
    state: str = Field("implemented", pattern=r"^(planned|implemented|verified|exception|not_applicable)$")
    notes: str | None = Field(None, max_length=10000)


def _meets(value: Decimal, objective: Decimal, comparison: str) -> bool:
    if comparison == "gte":
        return value >= objective
    if comparison == "lte":
        return value <= objective
    return value == objective


@router.post("/institutions/{institution_id}/reliability/slos", status_code=201)
async def create_slo(
    institution_id: UUID,
    body: SLOCreate,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "reliability.manage")
    await require_recent_reauthentication(current_session)
    duplicate = (
        await db.execute(
            select(SLODefinition).where(
                SLODefinition.institution_id == institution_id,
                SLODefinition.component_key == body.component_key,
                SLODefinition.indicator == body.indicator,
                SLODefinition.state == "active",
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="An active SLO already exists for this indicator.")
    row = SLODefinition(
        institution_id=institution_id,
        component_key=body.component_key,
        indicator=body.indicator,
        objective=body.objective,
        comparison=body.comparison,
        unit=body.unit,
        window_days=body.window_days,
        external_commitment=body.external_commitment,
        created_by=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "component_key": row.component_key, "indicator": row.indicator, "objective": row.objective, "comparison": row.comparison, "unit": row.unit, "external_commitment": row.external_commitment}


@router.post("/institutions/{institution_id}/reliability/measurements", status_code=201)
async def record_sli(
    institution_id: UUID,
    body: SLIMeasurementCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "reliability.manage")
    slo = (await db.execute(select(SLODefinition).where(SLODefinition.id == body.slo_id, SLODefinition.institution_id == institution_id, SLODefinition.state == "active"))).scalar_one_or_none()
    if slo is None:
        raise HTTPException(status_code=404, detail="SLO not found")
    if body.window_end <= body.window_start:
        raise HTTPException(status_code=422, detail="Measurement window is invalid.")
    row = SLIMeasurement(
        slo_id=slo.id,
        institution_id=institution_id,
        component_key=slo.component_key,
        indicator=slo.indicator,
        window_start=body.window_start,
        window_end=body.window_end,
        value=body.value,
        numerator=body.numerator,
        denominator=body.denominator,
        unit=slo.unit,
        dimensions=body.dimensions,
        source=body.source,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "value": row.value, "unit": row.unit, "meets_objective": _meets(row.value, slo.objective, slo.comparison)}


@router.get("/institutions/{institution_id}/reliability/dashboard")
async def reliability_dashboard(
    institution_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "reliability.read")
    slos = list((await db.execute(select(SLODefinition).where(SLODefinition.institution_id == institution_id, SLODefinition.state == "active"))).scalars())
    result = []
    for slo in slos:
        measurement = (await db.execute(select(SLIMeasurement).where(SLIMeasurement.slo_id == slo.id).order_by(SLIMeasurement.window_end.desc()).limit(1))).scalar_one_or_none()
        result.append({
            "id": slo.id,
            "component": slo.component_key,
            "indicator": slo.indicator,
            "objective": slo.objective,
            "comparison": slo.comparison,
            "unit": slo.unit,
            "external_commitment": slo.external_commitment,
            "latest": ({"value": measurement.value, "window_start": measurement.window_start, "window_end": measurement.window_end, "meets_objective": _meets(measurement.value, slo.objective, slo.comparison)} if measurement else None),
        })
    now = datetime.now(timezone.utc)
    queue_rows = list((await db.execute(select(Job.queue_name, Job.status, func.count(Job.id), func.min(Job.created_at)).join_from(Job, __import__('app.models.project', fromlist=['Project']).Project, Job.project_id == __import__('app.models.project', fromlist=['Project']).Project.id, isouter=True).where((__import__('app.models.project', fromlist=['Project']).Project.institution_id == institution_id) | (Job.project_id.is_(None))).group_by(Job.queue_name, Job.status))).all())
    return {
        "institution_id": institution_id,
        "slos": result,
        "queues": [{"queue": queue, "status": status, "count": count, "oldest_age_seconds": max(0, int((now - oldest).total_seconds())) if oldest else None} for queue, status, count, oldest in queue_rows],
        "thesis_content_used": False,
    }


@router.post("/institutions/{institution_id}/security/evidence", status_code=201)
async def create_security_evidence(
    institution_id: UUID,
    body: SecurityEvidenceCreate,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "security.read")
    await require_recent_reauthentication(current_session)
    row = SecurityRequirementEvidence(
        standard=body.standard,
        version=body.version,
        level=body.level,
        requirement_id=body.requirement_id,
        requirement_text=body.requirement_text,
        implementation=body.implementation,
        automated_test_reference=body.automated_test_reference,
        manual_evidence_reference=body.manual_evidence_reference,
        owner=body.owner,
        state=body.state,
        notes=body.notes,
        last_verified_at=datetime.now(timezone.utc) if body.state == "verified" else None,
        last_verified_by=current_user.id if body.state == "verified" else None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "requirement_id": row.requirement_id, "state": row.state, "last_verified_at": row.last_verified_at, "compliance_claim": False}


@router.get("/institutions/{institution_id}/security/evidence")
async def list_security_evidence(
    institution_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "security.read")
    rows = list((await db.execute(select(SecurityRequirementEvidence).order_by(SecurityRequirementEvidence.standard, SecurityRequirementEvidence.requirement_id))).scalars())
    return {"standard_claim": "Implementation evidence only; no certification or full compliance claim.", "rows": [{"id": row.id, "standard": row.standard, "version": row.version, "level": row.level, "requirement_id": row.requirement_id, "implementation": row.implementation, "automated_test_reference": row.automated_test_reference, "manual_evidence_reference": row.manual_evidence_reference, "owner": row.owner, "state": row.state, "last_verified_at": row.last_verified_at, "notes": row.notes} for row in rows]}
