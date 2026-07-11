"""Helpers for keeping immutable revision registries isolated.

Imported source/quote rows remain stored so an old manuscript revision can be
restored. Only manual rows (no import revision) plus rows belonging to the
currently active revision may participate in editing, verification or export.
"""

from __future__ import annotations

from typing import Iterable, TypeVar
from uuid import UUID


T = TypeVar("T")


def active_revision_rows(rows: Iterable[T], active_revision_id: UUID | None) -> list[T]:
    return [
        row
        for row in rows
        if getattr(row, "import_revision_id", None) is None
        or getattr(row, "import_revision_id", None) == active_revision_id
    ]


def active_resolution_rows(rows: Iterable[T], active_revision_id: UUID | None) -> list[T]:
    return [
        row
        for row in rows
        if getattr(row, "revision_id", None) is None
        or getattr(row, "revision_id", None) == active_revision_id
    ]
