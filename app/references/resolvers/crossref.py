"""Crossref resolver — authoritative for DOIs and journal metadata."""

from __future__ import annotations

import httpx

from app.references.resolvers._util import authors_to_registry, crossref_kind
from app.references.resolvers.base import ResolvedRecord

_BASE = "https://api.crossref.org/works/"


class CrossrefResolver:
    name = "crossref"

    def handles(self, id_kind: str) -> bool:
        return id_kind == "doi"

    async def resolve(
        self,
        client: httpx.AsyncClient,
        id_kind: str,
        id_value: str,
        hint: dict | None = None,
    ) -> ResolvedRecord | None:
        try:
            response = await client.get(f"{_BASE}{id_value}")
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            work = response.json().get("message") or {}
        except ValueError:
            return None
        if not work:
            return None

        kind = crossref_kind(str(work.get("type", "")))
        rec = ResolvedRecord(
            identifier_kind="doi",
            identifier_value=id_value,
            authority=self.name,
            registry_kind=kind,
            matched=True,
        )
        titles = work.get("title") or []
        rec.add("title", titles[0] if titles else None, 0.98)
        rec.add("author", authors_to_registry(work.get("author") or []), 0.95)
        containers = work.get("container-title") or []
        rec.add("container", containers[0] if containers else None, 0.95)
        rec.add("publisher", work.get("publisher"), 0.9)
        rec.add("volume", work.get("volume"), 0.9)
        rec.add("number", work.get("issue"), 0.9)
        rec.add("pages", work.get("page"), 0.85)
        rec.add("doi_or_url", work.get("DOI"), 0.99)

        issued = (work.get("issued") or {}).get("date-parts") or []
        if issued and issued[0]:
            rec.add("year", str(issued[0][0]), 0.95)

        # Retraction signal: Crossref marks retractions via update-to notices.
        for update in work.get("update-to") or []:
            if str(update.get("type", "")).lower() in {"retraction", "withdrawal"}:
                rec.retraction = {
                    "retracted": True,
                    "kind": update.get("type"),
                    "notice_doi": update.get("DOI"),
                    "source": "crossref",
                }
                break
        return rec
