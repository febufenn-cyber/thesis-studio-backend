"""arXiv resolver — preprints by arXiv id (Atom API)."""

from __future__ import annotations

import re
from defusedxml import ElementTree as ET  # nosec B314 - safe, entity-expansion-guarded parser

import httpx

from app.references.resolvers._util import authors_to_registry
from app.references.resolvers.base import ResolvedRecord

_API = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"


class ArxivResolver:
    name = "arxiv"

    def handles(self, id_kind: str) -> bool:
        return id_kind == "arxiv"

    async def resolve(
        self,
        client: httpx.AsyncClient,
        id_kind: str,
        id_value: str,
        hint: dict | None = None,
    ) -> ResolvedRecord | None:
        try:
            response = await client.get(_API, params={"id_list": id_value, "max_results": "1"})
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            return None
        entry = root.find(f"{_ATOM}entry")
        if entry is None:
            return None
        title_el = entry.find(f"{_ATOM}title")
        if title_el is None or not (title_el.text or "").strip():
            return None

        # Map arXiv preprints to a web source: title + site + stable abs URL. This
        # avoids inventing journal metadata (volume/issue) a preprint does not have.
        rec = ResolvedRecord(
            identifier_kind="arxiv",
            identifier_value=id_value,
            authority="arxiv",
            registry_kind="web",
            matched=True,
        )
        rec.add("title", re.sub(r"\s+", " ", title_el.text.strip()), 0.95)
        rec.add("site", "arXiv", 0.99)
        parts = [
            {"name": (a.find(f"{_ATOM}name").text or "").strip()}
            for a in entry.findall(f"{_ATOM}author")
            if a.find(f"{_ATOM}name") is not None
        ]
        rec.add("author", authors_to_registry(parts), 0.9)
        rec.add("url", f"https://arxiv.org/abs/{id_value}", 0.99)
        published = entry.find(f"{_ATOM}published")
        if published is not None and (published.text or "")[:4].isdigit():
            rec.add("pub_date", published.text[:10], 0.9)
            rec.add("year", published.text[:4], 0.9)
        return rec
