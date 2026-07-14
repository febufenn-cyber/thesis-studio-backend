"""Resolver protocol and the normalized record shape resolvers return.

A resolver takes a shared ``httpx.AsyncClient`` and an identifier, and returns a
``ResolvedRecord`` whose ``fields`` are already keyed by *registry* field names
(author, title, container, ...) so downstream merge/apply never has to guess a
mapping. Any transport error, 404, or unparseable body must resolve to ``None``,
never a partial-but-wrong record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

__all__ = ["FieldValue", "ResolvedRecord", "Resolver"]


@dataclass(frozen=True)
class FieldValue:
    """One resolved field value with its authority and confidence."""

    value: str
    authority: str
    confidence: float  # 0.0–1.0
    raw: str | None = None


@dataclass
class ResolvedRecord:
    """Normalized metadata from a single authority, keyed by registry field."""

    identifier_kind: str
    identifier_value: str
    authority: str
    fields: dict[str, FieldValue] = field(default_factory=dict)
    source_type: str | None = None
    registry_kind: str | None = None
    retraction: dict | None = None
    matched: bool = False

    def add(self, name: str, value: str | None, confidence: float, raw: str | None = None) -> None:
        """Record a field only when it has real content (never-guess)."""
        text = (value or "").strip()
        if not text:
            return
        self.fields[name] = FieldValue(
            value=text, authority=self.authority, confidence=confidence, raw=raw
        )


@runtime_checkable
class Resolver(Protocol):
    name: str

    def handles(self, id_kind: str) -> bool: ...

    async def resolve(
        self,
        client: httpx.AsyncClient,
        id_kind: str,
        id_value: str,
        hint: dict | None = None,
    ) -> ResolvedRecord | None: ...
