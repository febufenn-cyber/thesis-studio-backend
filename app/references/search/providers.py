"""OpenAlex and Crossref search adapters (keyless)."""

from __future__ import annotations

import httpx

from app.references.search.base import Candidate

_OPENALEX = "https://api.openalex.org/works"
_CROSSREF = "https://api.crossref.org/works"


def _authors_openalex(authorships: list) -> list[str]:
    names: list[str] = []
    for entry in authorships or []:
        author = (entry or {}).get("author") or {}
        name = author.get("display_name")
        if name:
            names.append(name)
    return names


class OpenAlexSearch:
    name = "openalex"

    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int) -> list[Candidate]:
        try:
            response = await client.get(_OPENALEX, params={"search": query, "per-page": str(limit)})
        except httpx.HTTPError:
            return []
        if response.status_code != 200:
            return []
        try:
            results = (response.json() or {}).get("results") or []
        except ValueError:
            return []
        candidates: list[Candidate] = []
        for i, work in enumerate(results):
            doi = (work.get("doi") or "").replace("https://doi.org/", "") or None
            location = work.get("primary_location") or {}
            source = location.get("source") or {}
            candidates.append(
                Candidate(
                    title=work.get("title") or work.get("display_name") or "",
                    authors=_authors_openalex(work.get("authorships") or []),
                    year=work.get("publication_year"),
                    container=source.get("display_name"),
                    doi=doi,
                    identifier=doi or work.get("id") or "",
                    authority="openalex",
                    score=1.0 - (i / max(1, limit)),
                )
            )
        return [c for c in candidates if c.identifier]


def _authors_crossref(authors: list) -> list[str]:
    names: list[str] = []
    for person in authors or []:
        family = (person or {}).get("family", "")
        given = (person or {}).get("given", "")
        if family and given:
            names.append(f"{family}, {given}")
        elif family:
            names.append(family)
    return names


class CrossrefSearch:
    name = "crossref"

    async def search(self, client: httpx.AsyncClient, query: str, *, limit: int) -> list[Candidate]:
        try:
            response = await client.get(_CROSSREF, params={"query": query, "rows": str(limit)})
        except httpx.HTTPError:
            return []
        if response.status_code != 200:
            return []
        try:
            items = ((response.json() or {}).get("message") or {}).get("items") or []
        except ValueError:
            return []
        candidates: list[Candidate] = []
        for i, work in enumerate(items):
            titles = work.get("title") or []
            containers = work.get("container-title") or []
            issued = (work.get("issued") or {}).get("date-parts") or []
            year = issued[0][0] if issued and issued[0] else None
            doi = work.get("DOI")
            candidates.append(
                Candidate(
                    title=titles[0] if titles else "",
                    authors=_authors_crossref(work.get("author") or []),
                    year=year,
                    container=containers[0] if containers else None,
                    doi=doi,
                    identifier=doi or "",
                    authority="crossref",
                    score=1.0 - (i / max(1, limit)),
                )
            )
        return [c for c in candidates if c.identifier]


SEARCH_REGISTRY = (OpenAlexSearch(), CrossrefSearch())
