"""De-identification + k-anonymity (docs/LLD.md 3.8)."""

from __future__ import annotations

from uuid import uuid4

from app.commercial.observability import opaque_identifier
from app.research.anonymize import anonymize_project, research_pseudonym
from app.research.corpus import k_anonymize


class _Project:
    def __init__(self):
        self.user_id = uuid4()
        self.id = uuid4()
        self.document_version = 3
        self.chapters = [{"blocks": [
            {"type": "paragraph", "origin": "human", "runs": [{"text": "SECRET prose"}]},
            {"type": "paragraph", "origin": "ai_proposal", "runs": [{"text": "more SECRET"}]},
            {"type": "marker", "kind": "VERIFY", "origin": "human"},
        ]}]
        self.meta = {
            "citation_style": "mla-9", "domain_profile": "phd_thesis", "locale": "",
            "candidate": {"name": "Jane Secret"}, "college": {"name": "Secret College"},
            "submission": {"year": 2024},
        }
        self.works_cited = [{"source_id": str(uuid4())}]


def test_anonymize_strips_all_pii_and_prose() -> None:
    payload = anonymize_project(_Project())
    blob = str(payload)
    assert "Jane Secret" not in blob
    assert "Secret College" not in blob
    assert "SECRET prose" not in blob
    assert payload["origin_counts"] == {"human": 2, "ai_proposal": 1}
    assert payload["marker_kinds"] == {"VERIFY": 1}
    assert payload["submission_decade"] == "2020s"
    assert "candidate" not in payload and "college" not in payload


def test_pseudonym_is_stable_and_unforgeable() -> None:
    uid = uuid4()
    a = research_pseudonym(uid)
    assert a == research_pseudonym(uid)  # stable
    assert a != research_pseudonym(uuid4())  # differs per user
    assert a != opaque_identifier(str(uid))  # not the bare identifier
    assert len(a) == 64


def test_k_anonymity_suppresses_small_buckets() -> None:
    records = [{"domain_profile": "phd_thesis", "citation_style": "mla-9", "locale": ""} for _ in range(3)]
    records += [{"domain_profile": "neurips_paper", "citation_style": "ieee-2021", "locale": ""} for _ in range(6)]
    kept, suppressed = k_anonymize(records, k=5)
    # Only the 6-member bucket survives.
    assert len(kept) == 6
    assert suppressed == 3
