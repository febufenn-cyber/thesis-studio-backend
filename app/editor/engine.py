"""Authoritative wrapper around the low-level command implementation.

Commands that can touch more than one container use a whole-document inverse.
That is intentionally conservative: undo must restore the exact prior state,
including chapter statuses and target-container ordering.
"""

from __future__ import annotations

from app.canonical.model import ThesisDocument
from app.editor.commands import CommandResult, apply_command as _apply_command


def apply_command(
    document: ThesisDocument,
    command_type: str,
    payload: dict,
    *,
    allow_internal: bool = False,
) -> CommandResult:
    before = document.model_dump(mode="json")
    result = _apply_command(
        document,
        command_type,
        payload,
        allow_internal=allow_internal,
    )
    if command_type == "move_block":
        result.inverse_command = {
            "command_type": "restore_document",
            "payload": {"document": before},
        }
    return result
