"""Tool-disabled structured Claude provider for grounded project AI runs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import GroundedAIOutput
from app.core.config import get_settings
from app.models.usage_event import UsageEvent
from app.services.claude_service import (
    ClaudeRateLimitError,
    ClaudeSubprocessError,
    _check_subprocess_outcome,
    _extract_cost,
)


log = logging.getLogger(__name__)
_EMPTY_MCP_CONFIG = str(Path(__file__).parents[1] / "services" / "empty_mcp_config.json")
_TIMEOUT_SECONDS = 600


class StructuredOutputError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    output: GroundedAIOutput
    usage: dict[str, Any]
    raw_text: str


def _extract_json(text: str) -> dict:
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise StructuredOutputError("AI response did not contain a JSON object.")
        try:
            value = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise StructuredOutputError("AI response JSON was malformed.") from exc
    if not isinstance(value, dict):
        raise StructuredOutputError("AI response must be one JSON object.")
    return value


class StructuredAIProvider:
    """One-shot JSON call with no tools, MCP, browsing or session persistence."""

    async def call(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        db: AsyncSession,
        user_id: UUID,
        task_mode: str,
    ) -> ProviderResult:
        settings = get_settings()
        fd, system_path = tempfile.mkstemp(suffix=".txt", prefix="robofox_ai_policy_")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(system_prompt)
        try:
            args = [
                settings.CLAUDE_CLI_PATH,
                "-p",
                "--model",
                model,
                "--tools",
                "",
                "--disable-slash-commands",
                "--no-session-persistence",
                "--strict-mcp-config",
                "--mcp-config",
                _EMPTY_MCP_CONFIG,
                "--system-prompt-file",
                system_path,
                "--output-format",
                "json",
            ]
            # The prompt carries the student's canonical content, sources and
            # quotations. Passing it via stdin instead of a CLI positional arg
            # keeps it out of the process table (`ps`, /proc/<pid>/cmdline) and
            # avoids ARG_MAX limits on large scopes. `claude -p` reads the prompt
            # from stdin when no positional prompt is supplied.
            log.info(
                "grounded AI subprocess mode=%s model=%s prompt_chars=%d",
                task_mode,
                model,
                len(user_prompt),
            )
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tempfile.gettempdir(),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=user_prompt.encode("utf-8")),
                    timeout=_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError as exc:
                proc.kill()
                await proc.wait()
                raise ClaudeSubprocessError(
                    f"grounded AI subprocess exceeded {_TIMEOUT_SECONDS}s timeout"
                ) from exc

            try:
                result_event = json.loads(stdout.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                raise StructuredOutputError("AI provider returned an unreadable envelope.") from exc
            _check_subprocess_outcome(proc.returncode, result_event, stderr)
            raw_text = str(result_event.get("result", ""))
            try:
                output = GroundedAIOutput.model_validate(_extract_json(raw_text))
            except ValidationError as exc:
                raise StructuredOutputError(
                    "AI response did not match the governed output schema."
                ) from exc

            usage_raw = result_event.get("usage") or {}
            usage = {
                "input_tokens": int(usage_raw.get("input_tokens", 0) or 0),
                "output_tokens": int(usage_raw.get("output_tokens", 0) or 0),
                "cached_input_tokens": int(usage_raw.get("cache_read_input_tokens", 0) or 0),
                "estimated_cost_usd": (
                    str(_extract_cost(result_event)) if _extract_cost(result_event) is not None else None
                ),
                "model": model,
            }
            db.add(
                UsageEvent(
                    user_id=user_id,
                    session_id=None,
                    model=model,
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    cached_input_tokens=usage["cached_input_tokens"],
                    estimated_cost_usd=(
                        Decimal(usage["estimated_cost_usd"])
                        if usage["estimated_cost_usd"] is not None
                        else None
                    ),
                    event_type=f"grounded_ai_{task_mode}"[:50],
                )
            )
            await db.flush()
            return ProviderResult(output=output, usage=usage, raw_text=raw_text)
        finally:
            try:
                os.unlink(system_path)
            except OSError:
                pass


def get_structured_ai_provider() -> StructuredAIProvider:
    return StructuredAIProvider()


__all__ = [
    "ClaudeRateLimitError",
    "ClaudeSubprocessError",
    "ProviderResult",
    "StructuredAIProvider",
    "StructuredOutputError",
    "get_structured_ai_provider",
]
