"""Phase 4 submission readiness, sealing, attestations and external review."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.collaboration.capabilities import require_project_capability
from app.collaboration.sealing import (
    SubmissionError,
    create_attestation,
    create_external_review_grant,
    resolve_external_review_grant,
    revoke_external_review_grant,
    seal_submission,
    submission_readiness,
    withdraw_submission,
)
from app.db.deps import get_db
from app.models.institutional_governance import ExternalReviewGrant, SubmissionPackage


router = APIRouter(tags=["submissions"])


class AttestationCreate(BaseModel):
    attestation_type: Literal[
        "student_authorship", "supervisor_workflow_approval", "operator_formatting_disclosure",
        "conflict_of_interest", "ai_policy_acknowledgement", "confidential_corpus_restriction",
    ]
    statement_version: str = Field(..., min_length=1, max_length=40)
    statement_text: str = Field(..., min_length=5, max_length=20000)
    accepted: bool
    context: dict = Field(default_factory=dict)


class SealRequest(BaseModel):
    note: str | None = Field(None, max_length=8000)


class WithdrawalRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=8000)


class ExternalGrantCreate(BaseModel):
    recipient_email: str = Field(..., min_length=3, max_length=255)
    expires_at: datetime
    permissions: list[Literal["sealed.read_metadata", "sealed.read_content", "sealed.download"]] = Field(default_factory=lambda: ["sealed.read_metadata", "sealed.read_content"])
    download_allowed: bool = False
    watermark: str | None = Field(None, max_length=300)


class ExternalAccessRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)


def _package_dict(row: SubmissionPackage, *, include_manifest: bool = True) -> dict:
    data = {
        "id": row.id, "project_id": row.project_id, "institution_id": row.institution_id,
        "department_id": row.department_id, "package_number": row.package_number,
        "state": row.state, "snapshot_id": row.snapshot_id, "document_version": row.document_version,
        "document_checksum": row.document_checksum, "profile_version_id": row.profile_version_id,
        "policy_version_id": row.policy_version_id, "package_checksum": row.package_checksum,
        "sealed_by": row.sealed_by, "sealed_at": row.sealed_at, "withdrawn_at": row.withdrawn_at,
        "withdrawal_reason": row.withdrawal_reason, "superseded_by_id": row.superseded_by_id,
    }
    if include_manifest:
        data["manifest"] = row.manifest
    return data


@router.get("/projects/{project_id}/submission-readiness")
async def get_submission_readiness(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.read_metadata")
    return await submission_readiness(db, access.project)


@router.post("/projects/{project_id}/attestations", status_code=201)
async def add_attestation(
    project_id: UUID,
    body: AttestationCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "submission.attest")
    if body.attestation_type == "student_authorship" and access.role != "student":
        raise HTTPException(status_code=409, detail="Only the student author can make the authorship attestation.")
    if body.attestation_type == "supervisor_workflow_approval" and access.role != "supervisor":
        raise HTTPException(status_code=409, detail="Only an assigned supervisor can make this workflow attestation.")
    try:
        row = await create_attestation(db, access.project, current_user.id, attestation_type=body.attestation_type, statement_version=body.statement_version, statement_text=body.statement_text, accepted=body.accepted, context=body.context)
    except SubmissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": row.id, "attestation_type": row.attestation_type, "user_id": row.user_id, "statement_version": row.statement_version, "accepted": row.accepted, "created_at": row.created_at, "legal_notice": "This is an authenticated workflow attestation, not a representation of a legally certified digital signature."}


@router.post("/projects/{project_id}/submission-packages", status_code=201)
async def create_submission_package(
    project_id: UUID,
    body: SealRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.transition_submission")
    try:
        row = await seal_submission(db, access.project, current_user.id, note=body.note)
    except SubmissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _package_dict(row)


@router.get("/projects/{project_id}/submission-packages")
async def list_submission_packages(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_project_capability(db, project_id, current_user, "project.read_metadata")
    rows = list((await db.execute(select(SubmissionPackage).where(SubmissionPackage.project_id == project_id).order_by(SubmissionPackage.package_number.desc()))).scalars())
    return [_package_dict(row, include_manifest=False) for row in rows]


@router.get("/projects/{project_id}/submission-packages/{package_id}")
async def read_submission_package(
    project_id: UUID,
    package_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_project_capability(db, project_id, current_user, "project.read_metadata")
    row = (await db.execute(select(SubmissionPackage).where(SubmissionPackage.id == package_id, SubmissionPackage.project_id == project_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Submission package not found")
    return _package_dict(row)


@router.post("/projects/{project_id}/submission-packages/{package_id}/withdraw")
async def withdraw_package(
    project_id: UUID,
    package_id: UUID,
    body: WithdrawalRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.transition_submission")
    row = (await db.execute(select(SubmissionPackage).where(SubmissionPackage.id == package_id, SubmissionPackage.project_id == project_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Submission package not found")
    try:
        return _package_dict(await withdraw_submission(db, row, access.project, current_user.id, body.reason))
    except SubmissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/projects/{project_id}/submission-packages/{package_id}/external-review", status_code=201)
async def add_external_review(
    project_id: UUID,
    package_id: UUID,
    body: ExternalGrantCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_project_capability(db, project_id, current_user, "project.transition_submission")
    package = (await db.execute(select(SubmissionPackage).where(SubmissionPackage.id == package_id, SubmissionPackage.project_id == project_id))).scalar_one_or_none()
    if package is None:
        raise HTTPException(status_code=404, detail="Submission package not found")
    try:
        row, token = await create_external_review_grant(db, package, current_user.id, recipient_email=body.recipient_email, expires_at=body.expires_at, permissions=body.permissions, download_allowed=body.download_allowed, watermark=body.watermark)
    except SubmissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": row.id, "recipient_email": row.recipient_email, "permissions": row.permissions, "download_allowed": row.download_allowed, "watermark": row.watermark, "expires_at": row.expires_at, "access_token": token, "token_notice": "The token is returned once. Send it only to the bound recipient; it is not included in audit logs or analytics."}


@router.delete("/projects/{project_id}/external-review/{grant_id}")
async def revoke_external_review(
    project_id: UUID,
    grant_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_project_capability(db, project_id, current_user, "project.transition_submission")
    row = (await db.execute(select(ExternalReviewGrant).join(SubmissionPackage, SubmissionPackage.id == ExternalReviewGrant.submission_package_id).where(ExternalReviewGrant.id == grant_id, SubmissionPackage.project_id == project_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="External review access not found")
    await revoke_external_review_grant(db, row, current_user.id)
    return {"id": row.id, "status": row.status, "revoked_at": row.revoked_at}


@router.post("/external-review/access")
async def external_review_access(
    body: ExternalAccessRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        grant, package, snapshot = await resolve_external_review_grant(db, body.token)
    except SubmissionError as exc:
        raise HTTPException(status_code=404, detail="External review access not found") from exc
    response = {
        "grant": {
            "recipient_email": grant.recipient_email,
            "permissions": grant.permissions,
            "watermark": grant.watermark,
            "download_allowed": grant.download_allowed,
            "expires_at": grant.expires_at,
        },
        "submission": _package_dict(package, include_manifest="sealed.read_metadata" in grant.permissions),
        "signature_notice": "Approvals shown are authenticated workflow records, not claims of legally certified signatures.",
    }
    if "sealed.read_content" in grant.permissions:
        response["canonical_document"] = snapshot.canonical_document
    return response
