"""ORCID identity verification (docs/LLD_MISSING_FEATURES.md MF3).

Lightweight: verify an ORCID iD exists via the public API before storing it. The
public API needs no credentials; a network failure fails closed (unverified).
"""

from __future__ import annotations

import re

import httpx

_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def is_well_formed(orcid: str) -> bool:
    return bool(_ORCID_RE.match(orcid.strip()))


class OrcidClient:
    def __init__(self, client: httpx.AsyncClient, base_url: str = "https://pub.orcid.org/v3.0") -> None:
        self._client = client
        self._base = base_url.rstrip("/")

    async def verify(self, orcid: str) -> bool:
        """Return True only if the ORCID is well-formed and resolves publicly."""
        return (await self.resolve(orcid)) is not None

    async def resolve(self, orcid: str) -> dict | None:
        """Return {orcid, name} from the public ORCID record, or None (fail-closed)."""
        if not is_well_formed(orcid):
            return None
        try:
            response = await self._client.get(
                f"{self._base}/{orcid}/person", headers={"Accept": "application/json"}
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json() or {}
        except ValueError:
            return None
        name = data.get("name") or {}
        given = ((name.get("given-names") or {}) or {}).get("value", "")
        family = ((name.get("family-name") or {}) or {}).get("value", "")
        full = " ".join(p for p in (given, family) if p).strip()
        return {"orcid": orcid, "name": full or None}
