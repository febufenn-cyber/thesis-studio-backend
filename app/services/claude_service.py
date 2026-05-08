"""Claude subprocess service.

Calls the Claude Code CLI as a subprocess (`claude -p ...`). Authentication is
managed by the CLI itself via Max OAuth (login once per host with `claude /login`).
The backend never reads or stores OAuth tokens.

Why subprocess and not the SDK:
- Single-user personal deployment fronted by Cloudflare Access; pay-per-use API
  pricing was the wrong cost shape, the Max subscription is.
- The CLI is the supported automation surface for Max accounts.

Tradeoffs encoded in the flag stack:
- `--strict-mcp-config` + empty config strips this host's personal MCP servers
  out of the prompt prefix.
- `--system-prompt-file` (replace, not append) drives the coaching personality
  cleanly. Tested: append mode glues onto Claude Code's full system prompt and
  costs ~5x more in cache_creation tokens for equivalent output.
- `--no-session-persistence` keeps Claude Code from writing session state to
  disk. Multi-turn history is embedded into each user prompt instead — see
  `_format_conversation`. Do not switch to `--continue`/`--resume`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.usage_event import UsageEvent


log = logging.getLogger(__name__)


_EMPTY_MCP_CONFIG = str(Path(__file__).parent / "empty_mcp_config.json")

_CHAT_TIMEOUT_SECONDS = 300
_COMPILE_TIMEOUT_SECONDS = 600


class ClaudeRateLimitError(RuntimeError):
    """Surface a 429 / Max-session-limit condition cleanly to the caller."""


class ClaudeSubprocessError(RuntimeError):
    """Generic non-zero exit or malformed CLI output."""


class ClaudeService:
    """Wrapper around `claude -p` for coaching chat and compile passes."""

    def __init__(self) -> None:
        settings = get_settings()
        self.cli_path = settings.CLAUDE_CLI_PATH

    async def stream_chat(
        self,
        *,
        system_blocks: list[dict[str, Any]],
        messages: list[dict[str, str]],
        db: AsyncSession,
        user_id: UUID,
        session_id: UUID,
        model: str | None = None,
        max_tokens: int = 2000,
    ) -> AsyncIterator[tuple[str, dict | None]]:
        """Stream a coaching chat completion.

        Yields (token_text, usage_dict_or_None) tuples; the final tuple has
        empty token text and a populated usage dict. Records a usage_events row
        and commits the DB before the final yield.
        """
        settings = get_settings()
        model = model or settings.CLAUDE_COACHING_MODEL

        system_prompt_text = "\n\n".join(
            block["text"]
            for block in system_blocks
            if block.get("type") == "text" and block.get("text")
        )

        if not messages or messages[-1].get("role") != "user":
            raise ValueError("messages must end with a user-role message")
        history = messages[:-1]
        current_message = messages[-1]["content"]
        user_prompt = self._format_conversation(history, current_message)

        sys_file = _write_temp_prompt(system_prompt_text)
        result_event: dict | None = None
        full_text = ""
        stderr_buf = bytearray()

        try:
            args = [
                self.cli_path, "-p",
                "--model", model,
                "--tools", "",
                "--disable-slash-commands",
                "--no-session-persistence",
                "--strict-mcp-config",
                "--mcp-config", _EMPTY_MCP_CONFIG,
                "--system-prompt-file", sys_file,
                "--output-format", "stream-json",
                "--include-partial-messages",
                "--verbose",
                user_prompt,
            ]

            log.info(
                "claude chat subprocess: model=%s history_turns=%d prompt_chars=%d",
                model, len(history), len(user_prompt),
            )

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tempfile.gettempdir(),
            )

            stderr_task = asyncio.create_task(_drain(proc.stderr, stderr_buf))
            deadline = time.monotonic() + _CHAT_TIMEOUT_SECONDS

            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    try:
                        line = await asyncio.wait_for(
                            proc.stdout.readline(), timeout=remaining,
                        )
                    except asyncio.TimeoutError:
                        raise
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue
                    try:
                        event = json.loads(line_str)
                    except json.JSONDecodeError:
                        log.warning("non-JSON line from claude CLI: %r", line_str[:200])
                        continue

                    ev_type = event.get("type")
                    if ev_type == "stream_event":
                        inner = event.get("event") or {}
                        if inner.get("type") == "content_block_delta":
                            delta = inner.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    full_text += text
                                    yield text, None
                    elif ev_type == "result":
                        result_event = event
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise ClaudeSubprocessError(
                    f"claude chat subprocess exceeded {_CHAT_TIMEOUT_SECONDS}s timeout"
                )
            finally:
                await stderr_task
                rc = await proc.wait()

            _check_subprocess_outcome(rc, result_event, bytes(stderr_buf))

            usage = result_event.get("usage", {}) if result_event else {}
            usage_dict = {
                "input_tokens": int(usage.get("input_tokens", 0) or 0),
                "output_tokens": int(usage.get("output_tokens", 0) or 0),
                "cached_input_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
                "model": model,
                "full_text": full_text,
            }

            await self._record_usage(
                db=db,
                user_id=user_id,
                session_id=session_id,
                model=model,
                input_tokens=usage_dict["input_tokens"],
                output_tokens=usage_dict["output_tokens"],
                cached_input_tokens=usage_dict["cached_input_tokens"],
                estimated_cost_usd=_extract_cost(result_event),
                event_type="chat",
            )
            await db.commit()

            yield "", usage_dict
        finally:
            try:
                os.unlink(sys_file)
            except OSError:
                pass

    async def call_compile(
        self,
        *,
        messages: list[dict[str, str]],
        system_prompt: str,
        db: AsyncSession,
        user_id: UUID,
        session_id: UUID,
        model: str | None = None,
        max_tokens: int = 16_000,
    ) -> str:
        """One-shot compile call. Returns the assistant's response text."""
        settings = get_settings()
        model = model or settings.CLAUDE_COMPILE_MODEL

        if not messages or messages[-1].get("role") != "user":
            raise ValueError("messages must end with a user-role message")
        history = messages[:-1]
        current_message = messages[-1]["content"]
        user_prompt = self._format_conversation(history, current_message)

        sys_file = _write_temp_prompt(system_prompt)
        try:
            args = [
                self.cli_path, "-p",
                "--model", model,
                "--tools", "",
                "--disable-slash-commands",
                "--no-session-persistence",
                "--strict-mcp-config",
                "--mcp-config", _EMPTY_MCP_CONFIG,
                "--system-prompt-file", sys_file,
                "--output-format", "json",
                user_prompt,
            ]

            log.info(
                "claude compile subprocess: model=%s history_turns=%d",
                model, len(history),
            )

            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tempfile.gettempdir(),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=_COMPILE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise ClaudeSubprocessError(
                    f"claude compile subprocess exceeded {_COMPILE_TIMEOUT_SECONDS}s timeout"
                )

            try:
                result_event = json.loads(stdout.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                log.error("claude compile produced unparseable JSON: %s", exc)
                raise ClaudeSubprocessError("compile produced unparseable JSON") from exc

            _check_subprocess_outcome(proc.returncode, result_event, stderr)

            text = result_event.get("result", "")
            usage = result_event.get("usage", {})

            await self._record_usage(
                db=db,
                user_id=user_id,
                session_id=session_id,
                model=model,
                input_tokens=int(usage.get("input_tokens", 0) or 0),
                output_tokens=int(usage.get("output_tokens", 0) or 0),
                cached_input_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
                estimated_cost_usd=_extract_cost(result_event),
                event_type="compile_doc",
            )
            await db.commit()

            return text
        finally:
            try:
                os.unlink(sys_file)
            except OSError:
                pass

    @staticmethod
    def _format_conversation(
        history: list[dict[str, str]],
        current_message: str,
    ) -> str:
        """Embed prior turns as XML-tagged context, then the current message.

        `claude -p` does not expose role-tagged multi-turn input under
        `--no-session-persistence`, so history is embedded in the user prompt.
        """
        if not history:
            return current_message

        parts = ["<conversation_history>"]
        for turn in history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            parts.append(f'  <turn role="{role}">{content}</turn>')
        parts.append("</conversation_history>")
        parts.append("")
        parts.append(current_message)
        parts.append("")
        parts.append(
            "Respond directly to the student's current message in your own voice. "
            "Do not output any tags or narration — just the response itself."
        )
        return "\n".join(parts)

    @staticmethod
    async def _record_usage(
        *,
        db: AsyncSession,
        user_id: UUID,
        session_id: UUID | None,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int,
        estimated_cost_usd: Decimal | None,
        event_type: str,
    ) -> None:
        db.add(UsageEvent(
            user_id=user_id,
            session_id=session_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            estimated_cost_usd=estimated_cost_usd,
            event_type=event_type,
        ))


async def _drain(stream: asyncio.StreamReader, into: bytearray) -> None:
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            break
        into.extend(chunk)


def _write_temp_prompt(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="claude_sysprompt_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _extract_cost(result_event: dict | None) -> Decimal | None:
    if not result_event:
        return None
    raw = result_event.get("total_cost_usd")
    if raw is None:
        return None
    try:
        return Decimal(str(raw)).quantize(Decimal("0.000001"))
    except (ValueError, ArithmeticError):
        return None


def _check_subprocess_outcome(
    returncode: int | None,
    result_event: dict | None,
    stderr_bytes: bytes,
) -> None:
    """Translate CLI failures into typed exceptions before recording usage."""
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    stderr_tail = stderr_text[-2000:] if stderr_text else ""

    if returncode != 0:
        log.error(
            "claude CLI exited with rc=%s; stderr tail: %s",
            returncode, stderr_tail,
        )
        if _looks_rate_limited(stderr_text, result_event):
            raise ClaudeRateLimitError("Claude Max rate limit reached")
        raise ClaudeSubprocessError(f"claude CLI exited rc={returncode}")

    if result_event is None:
        log.error(
            "claude CLI exited 0 but produced no result block; stderr tail: %s",
            stderr_tail,
        )
        raise ClaudeSubprocessError("claude CLI produced no result block")

    if result_event.get("is_error"):
        api_status = result_event.get("api_error_status")
        log.error("claude CLI reported API error: status=%s", api_status)
        if api_status == 429 or _looks_rate_limited(stderr_text, result_event):
            raise ClaudeRateLimitError(f"Claude API rate limit (status={api_status})")
        raise ClaudeSubprocessError(f"claude CLI API error (status={api_status})")


def _looks_rate_limited(stderr_text: str, result_event: dict | None) -> bool:
    if result_event:
        info = result_event.get("rate_limit_info") or {}
        if info.get("status") in {"rejected", "exceeded"}:
            return True
    needles = ("rate limit", "ratelimit", "429", "5_hour", "five_hour")
    text_lower = stderr_text.lower()
    return any(n in text_lower for n in needles)


_claude_service: ClaudeService | None = None


def get_claude_service() -> ClaudeService:
    global _claude_service
    if _claude_service is None:
        _claude_service = ClaudeService()
    return _claude_service
