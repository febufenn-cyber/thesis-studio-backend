"""Commercial AI provider adapters behind one governed structured-output contract.

The HTTP adapter targets a Robofox-compatible provider gateway rather than hard-coding
one vendor wire format. Secrets are referenced from environment variables or mounted
files; credential material is never stored in PostgreSQL.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import (
    ProviderResult,
    StructuredAIProvider,
    StructuredOutputError,
    get_structured_ai_provider,
)
from app.ai.schemas import GroundedAIOutput
from app.commercial.ai_capacity import ProviderRoute
from app.models.commercial import CostLedgerEntry
from app.models.usage_event import UsageEvent


class ProviderAdapterConfigurationError(RuntimeError):
    pass


def _secret(reference: str | None) -> str:
    if not reference:
        raise ProviderAdapterConfigurationError("AI provider credential reference is missing.")
    if reference.startswith("env:"):
        value = os.getenv(reference[4:], "")
    elif reference.startswith("file:"):
        path = Path(reference[5:])
        value = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    else:
        raise ProviderAdapterConfigurationError(
            "AI credentials must use an env: or file: secret reference."
        )
    if not value:
        raise ProviderAdapterConfigurationError("AI provider secret could not be resolved.")
    return value


def _endpoint(route: ProviderRoute) -> str:
    env_name = "AI_PROVIDER_" + route.slug.upper().replace("-", "_") + "_ENDPOINT"
    endpoint = os.getenv(env_name, "").strip()
    if not endpoint:
        raise ProviderAdapterConfigurationError(
            f"Configured HTTP provider endpoint is missing ({env_name})."
        )
    return endpoint


class ConfiguredHTTPProvider(StructuredAIProvider):
    """Call a provider gateway that returns Robofox's governed JSON envelope."""

    def __init__(self, route: ProviderRoute) -> None:
        self.route = route

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
        headers = {
            "Authorization": f"Bearer {_secret(self.route.credential_reference)}",
            "Content-Type": "application/json",
            "X-Robofox-Provider": self.route.slug,
        }
        payload = {
            "model": model,
            "task_mode": task_mode,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response_contract": "robofox.grounded_ai_output.v1",
            "tools": [],
            "external_browsing": False,
        }
        async with httpx.AsyncClient(timeout=600.0) as client:
            response = await client.post(_endpoint(self.route), headers=headers, json=payload)
        if response.status_code == 429:
            from app.ai.provider import ClaudeRateLimitError

            raise ClaudeRateLimitError("Configured AI provider rate limit reached.")
        if response.status_code >= 500:
            from app.ai.provider import ClaudeSubprocessError

            raise ClaudeSubprocessError("Configured AI provider is temporarily unavailable.")
        if response.status_code >= 400:
            raise ProviderAdapterConfigurationError(
                f"Configured AI provider rejected the request ({response.status_code})."
            )
        try:
            envelope: dict[str, Any] = response.json()
        except ValueError as exc:
            raise StructuredOutputError("AI provider returned a non-JSON response.") from exc
        output_payload = envelope.get("output", envelope)
        try:
            output = GroundedAIOutput.model_validate(output_payload)
        except ValidationError as exc:
            raise StructuredOutputError(
                "AI provider response did not match the governed output schema."
            ) from exc
        usage_raw = dict(envelope.get("usage") or {})
        usage = {
            "input_tokens": int(usage_raw.get("input_tokens", 0) or 0),
            "output_tokens": int(usage_raw.get("output_tokens", 0) or 0),
            "cached_input_tokens": int(usage_raw.get("cached_input_tokens", 0) or 0),
            "estimated_cost_usd": (
                str(usage_raw["estimated_cost_usd"])
                if usage_raw.get("estimated_cost_usd") is not None
                else None
            ),
            "model": model,
            "provider": self.route.slug,
        }
        estimated = (
            Decimal(usage["estimated_cost_usd"])
            if usage["estimated_cost_usd"] is not None
            else None
        )
        db.add(
            UsageEvent(
                user_id=user_id,
                session_id=None,
                model=model,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cached_input_tokens=usage["cached_input_tokens"],
                estimated_cost_usd=estimated,
                event_type=f"grounded_ai_{task_mode}"[:50],
            )
        )
        db.add(
            CostLedgerEntry(
                user_id=user_id,
                category="ai",
                provider=self.route.slug,
                operation=task_mode,
                quantity=Decimal(usage["input_tokens"] + usage["output_tokens"]),
                unit="tokens",
                currency="USD",
                estimated_cost_minor=int((estimated or Decimal(0)) * 100),
                metadata_json={
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "cached_input_tokens": usage["cached_input_tokens"],
                    "model": model,
                },
            )
        )
        await db.flush()
        return ProviderResult(
            output=output,
            usage=usage,
            raw_text=response.text,
        )


def provider_for_route(route: ProviderRoute) -> StructuredAIProvider:
    if route.adapter == "claude_cli":
        return get_structured_ai_provider()
    if route.adapter == "http_json":
        return ConfiguredHTTPProvider(route)
    raise ProviderAdapterConfigurationError(
        f"Unsupported AI provider adapter: {route.adapter}."
    )
