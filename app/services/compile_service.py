"""Compile service — background job that renders a thesis .docx from session messages.

Entry points:
  build_front_matter(session, user, institution) -> FrontMatter
      Assembles the institution/student header for the docx formatter.

  run_compile(file_id, session_id, user_id) -> None
      Background task.  Opens its own DB session (the request session is gone
      by the time BackgroundTasks fires), runs the full compile pipeline, and
      updates the File row with status "ready" or "failed".
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.formatter.compile_pipeline import parse_compile_json
from app.formatter.prompts import COMPILE_SYSTEM_PROMPT
from app.formatter.thesis_formatter import FrontMatter, render_thesis_docx
from app.models.file import File
from app.models.institution import Institution
from app.models.message import Message
from app.models.session import ThesisSession
from app.models.user import User
from app.services.claude_service import get_claude_service
from app.services.storage_service import get_storage_service


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Front-matter assembly
# ---------------------------------------------------------------------------


def build_front_matter(
    session: ThesisSession,
    user: User,
    institution: Institution,
) -> FrontMatter:
    """Assemble institution/student front-matter for the docx formatter.

    Degree-program lines stay at the dataclass defaults
    (MA in English Language and Literature).  Supervisor/HOD/study-period
    fields come from the session record; missing values are coerced to "".
    """
    email_local = user.email.split("@")[0]
    return FrontMatter(
        # Institution (required positional args)
        college_name=institution.name,
        college_address=institution.address,
        university_name=institution.university_name,
        department_name=session.department_override or institution.default_department,
        # Optional institution fields
        department_aided=institution.department_aided,
        short_address=institution.short_address or "",
        # Candidate
        student_full_name=user.full_name or email_local,
        register_number=user.register_number or "",
        # Supervisor / HOD from session
        supervisor_full_name=session.supervisor_full_name or "",
        supervisor_designation=session.supervisor_designation or "",
        hod_full_name=session.hod_full_name or "",
        study_period=session.study_period or "",
        # Thesis metadata
        thesis_title=session.title,
        submission_month_year=datetime.now().strftime("%B %Y"),
        submission_date="",
        place=institution.short_address or institution.name,
        # degree_program_line_1 / degree_program_line_2 use dataclass defaults
    )


# ---------------------------------------------------------------------------
# Background compile job
# ---------------------------------------------------------------------------


def _user_facing_error(exc: Exception) -> str:
    """Map an exception to a message safe to store and show to the file owner.

    Raw exception text can embed thesis content (parse errors quote the model
    output) or infrastructure details (boto errors include bucket names), so
    only known-safe, generic phrasings leave the server log.
    """
    from app.services.claude_service import ClaudeRateLimitError, ClaudeSubprocessError

    if isinstance(exc, ClaudeRateLimitError):
        return "The AI service is rate-limited right now. Please try again later."
    if isinstance(exc, ClaudeSubprocessError):
        return "The AI compile step failed. Please try again."
    if isinstance(exc, (BotoCoreError, ClientError)):
        return "Storing the compiled document failed. Please try again."
    if isinstance(exc, (KeyError, ValueError, TypeError)):
        return "The compile result could not be parsed into a document. Please try again."
    return "Compile failed unexpectedly. Please try again."


async def _mark_failed(db: AsyncSession, file_row: File, reason: str) -> None:
    """Set file_row.status to 'failed' and commit.

    Rolls back any in-flight transaction first so a prior DB error does not
    prevent the status update from landing.  Swallows its own errors.
    """
    try:
        await db.rollback()
        file_row.status = "failed"
        file_row.error_message = reason[:500]
        await db.commit()
    except Exception:
        log.exception(
            "_mark_failed: could not update file %s (reason: %s)", file_row.id, reason
        )


async def run_compile(file_id: UUID, session_id: UUID, user_id: UUID) -> None:
    """Background compile job.

    Opens its own DB session because FastAPI's BackgroundTasks run after the
    request session has been closed and its transaction has been committed.

    Steps:
      1. Load and validate File / ThesisSession / User / Institution rows.
      2. Build FrontMatter.
      3. Download institution logo (failure is non-fatal).
      4. Call Claude compile pass.
      5. Parse JSON → ThesisInput.
      6. Render docx in a thread pool (blocking python-docx call).
      7. Upload to storage.
      8. Mark File "ready".

    On any exception the File is marked "failed" and the error is logged.
    Temp files are cleaned up in the finally block regardless of outcome.
    """
    tmp_dir: str | None = None
    logo_path: str | None = None
    file_row: File | None = None

    async with AsyncSessionLocal() as db:
        try:
            # 1a. Load the File row.
            file_result = await db.execute(select(File).where(File.id == file_id))
            file_row = file_result.scalar_one_or_none()
            if file_row is None:
                log.error("run_compile: File %s not found — aborting", file_id)
                return

            # 1b. Load the session and verify ownership.
            session_result = await db.execute(
                select(ThesisSession).where(ThesisSession.id == session_id)
            )
            session = session_result.scalar_one_or_none()
            if session is None or session.user_id != user_id:
                await _mark_failed(db, file_row, "Session not found or user mismatch")
                return

            # 1c. Load the user.
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if user is None:
                await _mark_failed(db, file_row, "User not found")
                return

            # 1d. Load the effective institution (session override wins over user default).
            institution_id = session.institution_id_override or user.institution_id
            inst_result = await db.execute(
                select(Institution).where(Institution.id == institution_id)
            )
            institution = inst_result.scalar_one_or_none()
            if institution is None:
                await _mark_failed(
                    db, file_row, f"Institution {institution_id} not found"
                )
                return

            # 1e. Load conversation messages in chronological order.
            msg_result = await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.asc())
            )
            messages = [
                {"role": m.role, "content": m.content}
                for m in msg_result.scalars().all()
            ]

            if not messages:
                await _mark_failed(
                    db, file_row, "No messages in session — nothing to compile"
                )
                return

            # call_compile requires the final message to be a user turn.
            if messages[-1]["role"] != "user":
                messages = messages + [
                    {"role": "user", "content": "Please compile the thesis now."}
                ]

            # 2. Assemble front-matter.
            front_matter = build_front_matter(session, user, institution)

            # 3. Download institution logo — non-fatal on failure.
            storage = get_storage_service()
            if institution.logo_r2_key:
                try:
                    logo_path = await storage.download_to_temp(institution.logo_r2_key)
                except Exception:
                    log.warning(
                        "run_compile: logo download failed for key=%s; "
                        "proceeding without logo",
                        institution.logo_r2_key,
                    )
                    logo_path = None

            # 4. Prepare temp output path.
            tmp_dir = tempfile.mkdtemp(prefix="compile_")
            tmp_path = os.path.join(tmp_dir, f"{file_id}.docx")

            # 5. Call Claude compile pass (records a usage_events row internally).
            claude = get_claude_service()
            raw = await claude.call_compile(
                messages=messages,
                system_prompt=COMPILE_SYSTEM_PROMPT,
                db=db,
                user_id=user_id,
                session_id=session_id,
                model=get_settings().CLAUDE_COMPILE_MODEL,
            )

            log.info(
                "run_compile: Claude response received file_id=%s chars=%d",
                file_id,
                len(raw),
            )

            # 6. Parse JSON response → ThesisInput dataclasses.
            thesis_input = parse_compile_json(raw, front_matter)

            # 7. Render docx in thread pool (python-docx is synchronous/blocking).
            await asyncio.to_thread(
                render_thesis_docx,
                thesis_input,
                logo_path=logo_path,
                output_path=tmp_path,
            )

            # 8. Upload to storage and mark ready.
            key = f"files/{user_id}/{session_id}/{file_id}.docx"
            size = await storage.upload_file(tmp_path, key)

            file_row.r2_key = key
            file_row.size_bytes = size
            file_row.status = "ready"
            await db.commit()

            log.info(
                "run_compile: complete file_id=%s key=%s size=%d", file_id, key, size
            )

        except Exception as exc:
            # Full traceback stays in the server log; the stored/user-visible
            # message is sanitized (raw exception text can embed thesis
            # content or storage details).
            log.exception("run_compile: failed file_id=%s", file_id)
            if file_row is not None:
                await _mark_failed(db, file_row, _user_facing_error(exc))

        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            if logo_path:
                try:
                    os.unlink(logo_path)
                except OSError:
                    pass
