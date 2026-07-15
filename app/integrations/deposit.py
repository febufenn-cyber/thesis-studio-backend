"""Deposit targets (Zenodo) + protocol (docs/LLD_MISSING_FEATURES.md MF3).

Fail-closed: an empty credential is refused by the caller before any target is
constructed, so no network egress happens without configuration. The Zenodo
target defaults to the sandbox so a misconfiguration cannot publish to
production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx


class DepositError(RuntimeError):
    """A deposit step failed; the caller records status='failed'."""


@dataclass(frozen=True)
class DepositMeta:
    title: str
    creators: list[str]
    description: str = ""
    orcid: str | None = None


@dataclass(frozen=True)
class DepositResult:
    remote_id: str
    doi: str | None = None
    landing_url: str | None = None
    raw: dict | None = None


class DepositTarget(Protocol):
    name: str

    async def create_draft(self, meta: DepositMeta) -> DepositResult: ...
    async def upload_file(self, remote_id: str, path: str, filename: str, media_type: str) -> DepositResult: ...
    async def publish(self, remote_id: str) -> DepositResult: ...


class ZenodoTarget:
    name = "zenodo"

    def __init__(self, client: httpx.AsyncClient, token: str, base_url: str) -> None:
        self._client = client
        self._token = token
        self._base = base_url.rstrip("/")

    def _params(self) -> dict:
        return {"access_token": self._token}

    async def create_draft(self, meta: DepositMeta) -> DepositResult:
        payload = {
            "metadata": {
                "title": meta.title or "Untitled",
                "upload_type": "publication",
                "publication_type": "thesis",
                "description": meta.description or meta.title or "Deposited via Acadensia.",
                "creators": [
                    ({"name": name, "orcid": meta.orcid} if meta.orcid else {"name": name})
                    for name in (meta.creators or ["Unknown"])
                ],
            }
        }
        try:
            response = await self._client.post(
                f"{self._base}/api/deposit/depositions", params=self._params(), json=payload
            )
        except httpx.HTTPError as exc:
            raise DepositError(str(exc)) from exc
        if response.status_code not in (200, 201):
            raise DepositError(f"Zenodo draft failed: {response.status_code}")
        data = response.json()
        return DepositResult(remote_id=str(data["id"]), raw=data)

    async def upload_file(self, remote_id: str, path: str, filename: str, media_type: str) -> DepositResult:
        try:
            with open(path, "rb") as handle:
                files = {"file": (filename, handle, media_type)}
                response = await self._client.post(
                    f"{self._base}/api/deposit/depositions/{remote_id}/files",
                    params=self._params(),
                    files=files,
                )
        except (httpx.HTTPError, OSError) as exc:
            raise DepositError(str(exc)) from exc
        if response.status_code not in (200, 201):
            raise DepositError(f"Zenodo upload failed: {response.status_code}")
        return DepositResult(remote_id=remote_id, raw=response.json())

    async def publish(self, remote_id: str) -> DepositResult:
        try:
            response = await self._client.post(
                f"{self._base}/api/deposit/depositions/{remote_id}/actions/publish",
                params=self._params(),
            )
        except httpx.HTTPError as exc:
            raise DepositError(str(exc)) from exc
        if response.status_code not in (200, 202):
            raise DepositError(f"Zenodo publish failed: {response.status_code}")
        data = response.json()
        return DepositResult(
            remote_id=remote_id,
            doi=data.get("doi") or (data.get("metadata") or {}).get("prereserve_doi", {}).get("doi"),
            landing_url=(data.get("links") or {}).get("record_html"),
            raw=data,
        )
