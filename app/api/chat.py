"""Chat streaming endpoint.

POST /sessions/{id}/messages streams the assistant's response back to the
browser as Server-Sent Events. The user message is persisted before the
stream begins; the assistant message is persisted after the stream completes.

Per-user isolation: session ownership is verified BEFORE any Claude call,
so cross-user attempts can't even trigger an API charge.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_session
from app.db.deps import get_db
from app.formatter.prompts import build_coaching_system_blocks
from app.models.message import Message, ROLE_ASSISTANT, ROLE_USER
from app.schemas.session import MessageCreate
from app.services.claude_service import ClaudeService, get_claude_service


log = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["chat"])


@router.post("/{session_id}/messages")
async def send_message(
    session_id: UUID,
    body: MessageCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    claude: ClaudeService = Depends(get_claude_service),
) -> StreamingResponse:
    """Send a chat message and stream the assistant's response.

    Returns an SSE stream where each event is JSON like:
        {"type": "token", "text": "..."}
        {"type": "done", "usage": {...}}
        {"type": "error", "message": "..."}
    """
    # Ownership check — must come before anything else.
    session = await fetch_owned_session(db, session_id, current_user.id)

    # Pull the conversation history for this session.
    history_result = await db.execute(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.created_at.asc())
    )
    history_rows = list(history_result.scalars().all())
    history_messages = [
        {"role": m.role, "content": m.content} for m in history_rows
    ]

    # Persist the user message immediately so it survives stream errors.
    user_msg = Message(
        session_id=session.id,
        role=ROLE_USER,
        content=body.content,
    )
    db.add(user_msg)
    await db.commit()

    # Build the system prompt blocks (cacheable base + dynamic context).
    system_blocks = build_coaching_system_blocks(
        phase=session.phase,
        primary_text=session.primary_text,
        framework=session.framework,
        thesis_statement=session.thesis_statement,
        college_name=current_user.institution.name,
        supervisor_name=session.supervisor_full_name or "(not yet specified)",
        student_name=current_user.full_name or current_user.email.split("@")[0],
    )

    full_messages = [
        *history_messages,
        {"role": ROLE_USER, "content": body.content},
    ]

    async def event_stream():
        try:
            full_text = ""
            usage = None

            async for token, usage_dict in claude.stream_chat(
                system_blocks=system_blocks,
                messages=full_messages,
                db=db,
                user_id=current_user.id,
                session_id=session.id,
            ):
                if token:
                    full_text += token
                    yield _sse({"type": "token", "text": token})
                if usage_dict is not None:
                    usage = usage_dict
                    full_text = usage_dict["full_text"]

            # Persist the assistant's full reply after streaming.
            if usage is not None:
                db.add(Message(
                    session_id=session.id,
                    role=ROLE_ASSISTANT,
                    content=full_text,
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    cached_input_tokens=usage["cached_input_tokens"],
                    model=usage["model"],
                ))
                await db.commit()
            elif full_text:
                # The CLI exited without emitting a result block but did produce
                # text tokens. Persist what we have so the message is not lost,
                # and log a warning for investigation.
                log.warning(
                    "Claude CLI exited without a result block for session %s; "
                    "persisting %d chars with null token counts.",
                    session.id,
                    len(full_text),
                )
                db.add(Message(
                    session_id=session.id,
                    role=ROLE_ASSISTANT,
                    content=full_text,
                    input_tokens=None,
                    output_tokens=None,
                    cached_input_tokens=None,
                    model=None,
                ))
                await db.commit()

            yield _sse({
                "type": "done",
                "usage": {
                    "input_tokens": usage["input_tokens"] if usage else 0,
                    "output_tokens": usage["output_tokens"] if usage else 0,
                    "cached_input_tokens": usage["cached_input_tokens"] if usage else 0,
                },
            })
        except Exception as exc:
            log.exception("Chat streaming failed: %s", exc)
            yield _sse({
                "type": "error",
                "message": "An error occurred while generating the response.",
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable Nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse(payload: dict) -> str:
    """Format a dict as a Server-Sent Event line."""
    return f"data: {json.dumps(payload)}\n\n"
