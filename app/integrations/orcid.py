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
        if not is_well_formed(orcid):
            return False
        try:
            response = await self._client.get(
                f"{self._base}/{orcid}/person", headers={"Accept": "application/json"}
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 200
