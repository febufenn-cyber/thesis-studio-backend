"""OpenAlex resolver — broad open coverage; resolves DOIs and free-text search."""

from __future__ import annotations

import httpx

from app.references.resolvers._util import authors_to_registry, openalex_kind
from app.references.resolvers.base import ResolvedRecord

_WORK = "https://api.openalex.org/works/"
_SEARCH = "https://api.openalex.org/works"


def _authorships_to_parts(authorships: list[dict]) -> list[dict]:
    parts: list[dict] = []
    for entry in authorships:
        author = entry.get("author") or {}
        parts.append({"name": author.get("display_name", "")})
    return parts


def _record_from_work(work: dict, id_kind: str, id_value: str) -> ResolvedRecord | None:
    if not work:
        return None
    rec = ResolvedRecord(
        identifier_kind=id_kind,
        identifier_value=id_value,
        authority="openalex",
        registry_kind=openalex_kind(str(work.get("type", ""))),
        matched=True,
    )
    rec.add("title", work.get("title") or work.get("display_name"), 0.9)
    rec.add("author", authors_to_registry(_authorships_to_parts(work.get("authorships") or [])), 0.85)
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    rec.add("container", source.get("display_name"), 0.85)
    rec.add("publisher", source.get("host_organization_name"), 0.75)
    biblio = work.get("biblio") or {}
    rec.add("volume", biblio.get("volume"), 0.85)
    rec.add("number", biblio.get("issue"), 0.85)
    first, last = biblio.get("first_page"), biblio.get("last_page")
    if first and last:
        rec.add("pages", f"{first}-{last}", 0.8)
    elif first:
        rec.add("pages", str(first), 0.7)
    year = work.get("publication_year")
    if year:
        rec.add("year", str(year), 0.9)
    doi = work.get("doi")
    if doi:
        rec.add("doi_or_url", doi.replace("https://doi.org/", ""), 0.9)
    if work.get("is_retracted"):
        rec.retraction = {"retracted": True, "kind": "retraction", "source": "openalex"}
    return rec


class OpenAlexResolver:
    name = "openalex"

    def handles(self, id_kind: str) -> bool:
        return id_kind in {"doi", "freetext"}

    async def resolve(
        self,
        client: httpx.AsyncClient,
        id_kind: str,
        id_value: str,
        hint: dict | None = None,
    ) -> ResolvedRecord | None:
        try:
            if id_kind == "doi":
                response = await client.get(f"{_WORK}doi:{id_value}")
                if response.status_code != 200:
                    return None
                return _record_from_work(response.json(), id_kind, id_value)
            # free-text: search, take the top hit only if unambiguous
            query = (hint or {}).get("query", "")
            if not query:
                return None
            response = await client.get(
                _SEARCH, params={"search": query, "per-page": "2"}
            )
            if response.status_code != 200:
                return None
            results = (response.json() or {}).get("results") or []
            if len(results) != 1 and not results:
                return None
            return _record_from_work(results[0], id_kind, id_value) if results else None
        except (httpx.HTTPError, ValueError):
            return None
