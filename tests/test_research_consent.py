"""Research consent gate + governance (docs/LLD.md 3.8)."""

from __future__ import annotations

import pytest

from app.research.consent import (
    grant_research_consent,
    has_research_consent,
    revoke_research_consent,
)
from app.research.corpus import ResearchGovernanceError, build_corpus

pytestmark = pytest.mark.asyncio

_TERMS = "2026-07"  # matches conftest RESEARCH_TERMS_VERSION


async def test_deny_by_default_without_consent(db_session, user_a) -> None:
    assert await has_research_consent(db_session, user_a.id, "revision_history") is False


async def test_grant_then_has_consent(db_session, user_a) -> None:
    await grant_research_consent(
        db_session, user_id=user_a.id, scope="revision_history", terms_version=_TERMS
    )
    assert await has_research_consent(db_session, user_a.id, "revision_history") is True
    # 'all' scope covers a specific scope query.
    await grant_research_consent(db_session, user_id=user_a.id, scope="all", terms_version=_TERMS)
    assert await has_research_consent(db_session, user_a.id, "citation_patterns") is True


async def test_revoke_removes_consent(db_session, user_a) -> None:
    await grant_research_consent(
        db_session, user_id=user_a.id, scope="revision_history", terms_version=_TERMS
    )
    assert await has_research_consent(db_session, user_a.id, "revision_history") is True
    revoked = await revoke_research_consent(db_session, user_id=user_a.id, scope="revision_history")
    assert revoked == 1
    assert await has_research_consent(db_session, user_a.id, "revision_history") is False


async def test_stale_terms_version_is_not_consent(db_session, user_a) -> None:
    await grant_research_consent(
        db_session, user_id=user_a.id, scope="revision_history", terms_version="2020-01-old"
    )
    # Current terms is _TERMS, so the old grant does not count.
    assert await has_research_consent(db_session, user_a.id, "revision_history") is False


async def test_corpus_export_fails_closed_without_governance(db_session) -> None:
    # RESEARCH_CORPUS_ENABLED / ETHICS_APPROVAL_REF are off by default.
    with pytest.raises(ResearchGovernanceError):
        await build_corpus(db_session)
