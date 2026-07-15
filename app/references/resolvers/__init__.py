"""Bibliographic resolver registry.

An ordered tuple of resolvers behind one ``Resolver`` protocol, mirroring the
citation-style registry pattern. Order encodes authority precedence: Crossref
(authoritative for DOIs / journal metadata) → OpenAlex (broad, open) → arXiv
(preprints) → OpenLibrary (books by ISBN). Additional authorities
(Semantic Scholar, Unpaywall) can be appended without touching callers.
"""

from __future__ import annotations

from app.references.resolvers.arxiv import ArxivResolver
from app.references.resolvers.base import FieldValue, ResolvedRecord, Resolver
from app.references.resolvers.crossref import CrossrefResolver
from app.references.resolvers.openalex import OpenAlexResolver
from app.references.resolvers.openlibrary import OpenLibraryResolver

REGISTRY: tuple[Resolver, ...] = (
    CrossrefResolver(),
    OpenAlexResolver(),
    ArxivResolver(),
    OpenLibraryResolver(),
)

# Static precedence used to break confidence ties during reconciliation.
AUTHORITY_RANK: dict[str, int] = {
    "crossref": 4,
    "openalex": 3,
    "arxiv": 2,
    "openlibrary": 2,
}

__all__ = [
    "REGISTRY",
    "AUTHORITY_RANK",
    "Resolver",
    "ResolvedRecord",
    "FieldValue",
]
