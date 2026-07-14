"""DB-backed resolution cache (``resolution_records``).

Absorbs re-runs and rate-limited batch imports: a resolved identifier is read
from Postgres instead of re-hitting the authorities until its TTL expires.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.resolution_record import ResolutionRecord
from app.references.resolvers.base import ResolvedRecord


def _ttl_days() -> int:
    return int(getattr(get_settings(), "RESOLUTION_TTL_DAYS", 30))


async def get(db: AsyncSession, id_kind: str, id_value: str) -> ResolutionRecord | None:
    """Return a non-expired cached record for the identifier, if any."""
    row = (
        await db.execute(
            select(ResolutionRecord).where(
                ResolutionRecord.identifier_kind == id_kind,
                ResolutionRecord.identifier_value == id_value,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
        return None
    return row


async def put(
    db: AsyncSession,
    *,
    id_kind: str,
    id_value: str,
    status: str,
    merged: ResolvedRecord | None,
    authorities_tried: list[str],
) -> ResolutionRecord:
    """Insert or update the cache row for an identifier."""
    row = (
        await db.execute(
            select(ResolutionRecord).where(
                ResolutionRecord.identifier_kind == id_kind,
                ResolutionRecord.identifier_value == id_value,
            )
        )
    ).scalar_one_or_none()

    canonical: dict = {}
    provenance: dict = {}
    source_type = None
    registry_kind = None
    retraction = None
    if merged is not None:
        for name, fv in merged.fields.items():
            canonical[name] = fv.value
            provenance[name] = {
                "authority": fv.authority,
                "confidence": fv.confidence,
                "raw": fv.raw,
            }
        source_type = merged.source_type
        registry_kind = merged.registry_kind
        retraction = merged.retraction

    expires_at = datetime.now(timezone.utc) + timedelta(days=_ttl_days())

    if row is None:
        row = ResolutionRecord(
            identifier_kind=id_kind,
            identifier_value=id_value,
            status=status,
            canonical=canonical,
            provenance=provenance,
            candidates=[],
            retraction=retraction,
            authorities_tried=authorities_tried,
            source_type=source_type,
            registry_kind=registry_kind,
            expires_at=expires_at,
        )
        db.add(row)
    else:
        row.status = status
        row.canonical = canonical
        row.provenance = provenance
        row.retraction = retraction
        row.authorities_tried = authorities_tried
        row.source_type = source_type
        row.registry_kind = registry_kind
        row.expires_at = expires_at
    await db.flush()
    return row
