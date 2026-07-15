"""Meaning-level diff between two canonical document versions (docs/LLD.md 3.6).

Matches blocks by their stable ``BlockIdentity.id`` across chapters and front
matter and classifies each as added / removed / moved / meaning_changed /
formatting_only / unchanged. Meaning is a normalized signature of the block's
text (case/whitespace/citation-punctuation folded), so a genuine reword diverges
where a pure formatting change does not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.canonical.model import ThesisDocument
from app.collaboration.workflow import block_text

ChangeClass = Literal["added", "removed", "moved", "meaning_changed", "formatting_only", "unchanged"]


@dataclass(frozen=True)
class BlockDiffEntry:
    block_id: str
    change: ChangeClass
    base_position: int | None
    head_position: int | None


@dataclass(frozen=True)
class DiffResult:
    entries: list[BlockDiffEntry] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "entries": [
                {
                    "block_id": e.block_id,
                    "change": e.change,
                    "base_position": e.base_position,
                    "head_position": e.head_position,
                }
                for e in self.entries
            ],
        }


def _signature(block: dict) -> str:
    text = block_text(block).casefold()
    text = re.sub(r"[\s ]+", " ", text)
    text = re.sub(r"[(),.;:\[\]]", "", text)
    return text.strip()


def _raw(block: dict) -> str:
    return block_text(block)


def _index(document: ThesisDocument) -> dict[str, tuple[int, dict]]:
    out: dict[str, tuple[int, dict]] = {}
    position = 0
    for chapter in document.chapters:
        for block in chapter.blocks:
            out[str(block.id)] = (position, block.model_dump(mode="json"))
            position += 1
    for entry in document.front_matter:
        for block in entry.body_blocks:
            out[str(block.id)] = (position, block.model_dump(mode="json"))
            position += 1
    return out


def semantic_diff(base: ThesisDocument, head: ThesisDocument) -> DiffResult:
    base_index = _index(base)
    head_index = _index(head)
    entries: list[BlockDiffEntry] = []

    for block_id, (head_pos, head_block) in head_index.items():
        if block_id not in base_index:
            entries.append(BlockDiffEntry(block_id, "added", None, head_pos))
            continue
        base_pos, base_block = base_index[block_id]
        if _signature(base_block) == _signature(head_block):
            if base_pos != head_pos:
                entries.append(BlockDiffEntry(block_id, "moved", base_pos, head_pos))
            elif _raw(base_block) != _raw(head_block):
                entries.append(BlockDiffEntry(block_id, "formatting_only", base_pos, head_pos))
            else:
                entries.append(BlockDiffEntry(block_id, "unchanged", base_pos, head_pos))
        else:
            entries.append(BlockDiffEntry(block_id, "meaning_changed", base_pos, head_pos))

    for block_id, (base_pos, _block) in base_index.items():
        if block_id not in head_index:
            entries.append(BlockDiffEntry(block_id, "removed", base_pos, None))

    summary: dict[str, int] = {}
    for entry in entries:
        summary[entry.change] = summary.get(entry.change, 0) + 1
    return DiffResult(entries=entries, summary=summary)
