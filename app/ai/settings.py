"""Non-secret Phase 3 AI governance and capacity settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


@dataclass(frozen=True)
class AISettings:
    global_enabled: bool
    max_context_chars: int
    recent_thread_messages: int
    user_concurrent_limit: int
    project_queue_limit: int
    daily_run_limit: int
    daily_strong_run_limit: int
    max_proposal_operations: int


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings(
        global_enabled=_bool("AI_GLOBAL_ENABLED", True),
        max_context_chars=_int("AI_MAX_CONTEXT_CHARS", 60_000, minimum=8_000),
        recent_thread_messages=_int("AI_RECENT_THREAD_MESSAGES", 8),
        user_concurrent_limit=_int("AI_USER_CONCURRENT_LIMIT", 1),
        project_queue_limit=_int("AI_PROJECT_QUEUE_LIMIT", 3),
        daily_run_limit=_int("AI_DAILY_RUN_LIMIT", 30),
        daily_strong_run_limit=_int("AI_DAILY_STRONG_RUN_LIMIT", 5),
        max_proposal_operations=_int("AI_MAX_PROPOSAL_OPERATIONS", 20),
    )
