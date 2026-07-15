"""Literature discovery integration (docs/LLD_MISSING_FEATURES.md MF1).

Query upstream authorities (OpenAlex, Crossref) for candidates and let the user
add one directly as a verified registry Source via the Phase 1 resolver. Acadensia
stores no corpus — search results are ephemeral; only an *added* source persists,
and it is resolver-verified, never guessed.
"""

from __future__ import annotations

from app.references.search.base import Candidate, SearchProvider
from app.references.search.service import add_candidate, search

__all__ = ["Candidate", "SearchProvider", "search", "add_candidate"]
