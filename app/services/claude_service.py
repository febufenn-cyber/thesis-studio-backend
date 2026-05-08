"""Anthropic Claude API service.

Centralizes all Claude API calls so:
- Prompt caching is applied uniformly.
- Usage events are recorded on every call (required for cost tracking).
- Models are selected via config, never hardcoded in routes.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.usage_event import UsageEvent


log = logging.getLogger(__name__)


# Pricing per 1M tokens in USD. Update when Anthropic changes prices.
# Source: https://www.anthropic.com/pricing (verified May 2026).
_PRICING: dict[str, dict[str, Decimal]] = {
    "claude-sonnet-4-5": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
        "cache_read": Decimal("0.30"),
    },
    "claude-opus-4-7": {
        "input": Decimal("5.00"),
        "output": Decimal("25.00"),
        "cache_read": Decimal("0.50"),
    },
    "claude-haiku-4-5-20251001": {
        "input": Decimal("1.00"),
        "output": Decimal("5.00"),
        "cache_read": Decimal("0.10"),
    },
}


class ClaudeService:
    """Wrapper around AsyncAnthropic with our usage-tracking semantics."""

    def __init__(self) -> None:
        settings = get_settings()
        self.client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

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
        """Stream a chat completion. Yields (token_text, usage_dict_or_None) tuples.

        The last yielded item has empty token text and a populated usage dict.
        Usage is also recorded to the DB before the final yield.
        """
        settings = get_settings()
        model = model or settings.CLAUDE_COACHING_MODEL

        full_text_parts: list[str] = []
        usage_dict: dict | None = None

        async with self.client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                full_text_parts.append(text)
                yield text, None

            final = await stream.get_final_message()
            usage = final.usage

            usage_dict = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cached_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
                "model": model,
                "full_text": "".join(full_text_parts),
            }

        # Record usage before signalling done.
        await self._record_usage(
            db=db,
            user_id=user_id,
            session_id=session_id,
            model=model,
            input_tokens=usage_dict["input_tokens"],
            output_tokens=usage_dict["output_tokens"],
            cached_input_tokens=usage_dict["cached_input_tokens"],
            event_type="chat",
        )
        await db.commit()

        yield "", usage_dict

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
        """One-shot non-streaming call for the thesis compile pass.

        Returns the assistant's response text. Records a usage event.
        """
        settings = get_settings()
        model = model or settings.CLAUDE_COMPILE_MODEL

        response = await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )

        text = "".join(b.text for b in response.content if b.type == "text")

        await self._record_usage(
            db=db,
            user_id=user_id,
            session_id=session_id,
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_input_tokens=getattr(
                response.usage, "cache_read_input_tokens", 0
            ) or 0,
            event_type="compile_doc",
        )
        await db.commit()

        return text

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
        event_type: str,
    ) -> None:
        """Insert a UsageEvent row with computed cost."""
        cost = _compute_cost(model, input_tokens, output_tokens, cached_input_tokens)
        db.add(UsageEvent(
            user_id=user_id,
            session_id=session_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            estimated_cost_usd=cost,
            event_type=event_type,
        ))


def _compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
) -> Decimal | None:
    """Compute the USD cost of a single API call. Returns None if model unknown."""
    pricing = _PRICING.get(model)
    if pricing is None:
        log.warning("Unknown model in pricing table: %s", model)
        return None

    # Cached input bills at the cache-read rate; non-cached input at the full rate.
    fresh_input = max(0, input_tokens - cached_input_tokens)

    cost = (
        (Decimal(fresh_input) / 1_000_000) * pricing["input"]
        + (Decimal(cached_input_tokens) / 1_000_000) * pricing["cache_read"]
        + (Decimal(output_tokens) / 1_000_000) * pricing["output"]
    )
    return cost.quantize(Decimal("0.000001"))


# Module-level singleton — one Anthropic client per process.
_claude_service: ClaudeService | None = None


def get_claude_service() -> ClaudeService:
    """FastAPI dependency that returns the shared ClaudeService instance."""
    global _claude_service
    if _claude_service is None:
        _claude_service = ClaudeService()
    return _claude_service
