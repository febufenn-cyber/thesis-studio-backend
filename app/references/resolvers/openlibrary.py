"""OpenLibrary resolver — books by ISBN (no API key required)."""

from __future__ import annotations

import httpx

from app.references.resolvers._util import authors_to_registry
from app.references.resolvers.base import ResolvedRecord

_API = "https://openlibrary.org/api/books"


class OpenLibraryResolver:
    name = "openlibrary"

    def handles(self, id_kind: str) -> bool:
        return id_kind == "isbn"

    async def resolve(
        self,
        client: httpx.AsyncClient,
        id_kind: str,
        id_value: str,
        hint: dict | None = None,
    ) -> ResolvedRecord | None:
        params = {"bibkeys": f"ISBN:{id_value}", "format": "json", "jscmd": "data"}
        try:
            response = await client.get(_API, params=params)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            payload = response.json() or {}
        except ValueError:
            return None
        book = payload.get(f"ISBN:{id_value}")
        if not book:
            return None

        rec = ResolvedRecord(
            identifier_kind="isbn",
            identifier_value=id_value,
            authority="openlibrary",
            registry_kind="book",
            matched=True,
        )
        rec.add("title", book.get("title"), 0.9)
        parts = [{"name": a.get("name", "")} for a in book.get("authors") or []]
        rec.add("author", authors_to_registry(parts), 0.85)
        publishers = book.get("publishers") or []
        if publishers:
            rec.add("publisher", publishers[0].get("name"), 0.85)
        publish_date = book.get("publish_date") or ""
        year = "".join(c for c in publish_date if c.isdigit())[-4:]
        if len(year) == 4:
            rec.add("year", year, 0.8)
        return rec
