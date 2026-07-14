"""Search provider protocol and the ephemeral candidate shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

__all__ = ["Candidate", "SearchProvider"]


@dataclass(frozen=True)
class Candidate:
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    container: str | None = None
    doi: str | None = None
    identifier: str = ""  # seed for resolve_one: a DOI, else a resolvable URL/title
    authority: str = ""
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "container": self.container,
            "doi": self.doi,
            "identifier": self.identifier,
            "authority": self.authority,
            "score": self.score,
        }


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int) -> list[Candidate]: ...
