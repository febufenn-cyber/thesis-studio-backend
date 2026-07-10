"""Compile & download flow tests.

Covers the Phase 3 surface:
- POST /sessions/{id}/compile — auth, isolation, guards, happy path
- GET  /sessions/{id}/files    — isolation
- GET  /files/{id}/download    — isolation, readiness, local-backend serving
- run_compile background job   — end-to-end with a mocked Claude call,
  the real (locked) formatter, and the local storage backend.

The run_compile test uses the app's own AsyncSessionLocal (real commits on
the test database, outside the per-test savepoint) because that is exactly
how the background task behaves in production; it cleans up after itself.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from docx import Document
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file import File
from app.models.institution import Institution
from app.models.message import ROLE_ASSISTANT, ROLE_USER, Message
from app.models.session import ThesisSession
from app.models.user import User
from tests.conftest import auth_cookie


pytestmark = pytest.mark.asyncio

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

MINIMAL_COMPILE_JSON = json.dumps(
    {
        "abstract": "This study examines postcolonial identity in the novel.",
        "keywords": ["postcolonialism", "identity"],
        "acknowledgement": "The candidate thanks the supervisor for guidance.",
        "chapters": [
            {
                "number_roman": "I",
                "title": "INTRODUCTION",
                "intro_paragraphs": [
                    "The novel under study interrogates the colonial encounter.",
                    "This chapter situates the author and outlines the argument.",
                ],
                "sections": [],
            }
        ],
        "works_cited": [
            "Achebe, Chinua. *Things Fall Apart*. Heinemann, 1958.",
        ],
    }
)


async def _seed_session_with_reply(
    db: AsyncSession, user: User, title: str = "Postcolonial identity thesis"
) -> ThesisSession:
    """Create a session owned by *user* with one user+assistant message pair."""
    session = ThesisSession(user_id=user.id, title=title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    db.add_all(
        [
            Message(session_id=session.id, role=ROLE_USER, content="Help me plan."),
            Message(
                session_id=session.id,
                role=ROLE_ASSISTANT,
                content="Let us begin with your primary text.",
            ),
        ]
    )
    await db.commit()
    return session


# ---------------------------------------------------------------------------
# POST /sessions/{id}/compile
# ---------------------------------------------------------------------------


async def test_compile_unauthenticated_returns_401(client: AsyncClient) -> None:
    """No JWT cookie → 401."""
    response = await client.post(f"/sessions/{uuid4()}/compile")
    assert response.status_code == 401


async def test_compile_other_users_session_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """User A must not be able to trigger a compile on User B's session."""
    bobs_session = await _seed_session_with_reply(db_session, user_b)

    response = await client.post(
        f"/sessions/{bobs_session.id}/compile",
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 404


async def test_compile_without_assistant_reply_returns_409(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A session with no assistant messages has nothing to compile."""
    session = ThesisSession(user_id=user_a.id, title="Empty session")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    response = await client.post(
        f"/sessions/{session.id}/compile",
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 409
    assert "Nothing to compile" in response.json()["detail"]


async def test_compile_happy_path_creates_file_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """202 response, File row in 'compiling' state, background task scheduled."""
    session = await _seed_session_with_reply(db_session, user_a)

    calls: list[tuple] = []

    async def _fake_run_compile(*args) -> None:
        calls.append(args)

    # Patch the reference the router passes to BackgroundTasks.
    monkeypatch.setattr("app.api.compile.run_compile", _fake_run_compile)

    response = await client.post(
        f"/sessions/{session.id}/compile",
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "compiling"
    assert body["filename"].endswith(".docx")
    assert "Test" in body["filename"]  # from "Alice Test"

    result = await db_session.execute(
        select(File).where(File.session_id == session.id)
    )
    file_row = result.scalar_one()
    assert file_row.status == "compiling"
    assert file_row.r2_key is None
    assert file_row.user_id == user_a.id

    # BackgroundTasks run after the response is sent; the stub must have fired.
    assert len(calls) == 1


async def test_compile_with_blank_full_name_uses_fallback_filename(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace-only full_name must not crash the filename builder."""
    user = User(
        email=f"blank-{uuid4().hex[:8]}@test.edu",
        full_name="   ",
        institution_id=test_institution.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    session = await _seed_session_with_reply(db_session, user)

    async def _noop(*args) -> None:
        return None

    monkeypatch.setattr("app.api.compile.run_compile", _noop)

    response = await client.post(
        f"/sessions/{session.id}/compile",
        cookies=auth_cookie(user),
    )
    assert response.status_code == 202
    assert response.json()["filename"].startswith("Thesis_")


async def test_second_compile_while_running_returns_409(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """The per-session serialisation guard rejects concurrent compiles."""
    session = await _seed_session_with_reply(db_session, user_a)
    db_session.add(
        File(
            session_id=session.id,
            user_id=user_a.id,
            filename="in_progress.docx",
            file_type="docx",
            r2_key=None,
            status="compiling",
        )
    )
    await db_session.commit()

    response = await client.post(
        f"/sessions/{session.id}/compile",
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /sessions/{id}/files
# ---------------------------------------------------------------------------


async def test_files_list_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """Owner sees their files; a cross-user request gets 404."""
    session = await _seed_session_with_reply(db_session, user_a)
    db_session.add(
        File(
            session_id=session.id,
            user_id=user_a.id,
            filename="Test_MA_Dissertation.docx",
            file_type="docx",
            r2_key="files/x/y/z.docx",
            status="ready",
            size_bytes=12345,
        )
    )
    await db_session.commit()

    owner = await client.get(
        f"/sessions/{session.id}/files", cookies=auth_cookie(user_a)
    )
    assert owner.status_code == 200
    files = owner.json()
    assert len(files) == 1
    assert files[0]["status"] == "ready"
    assert files[0]["size_bytes"] == 12345

    attacker = await client.get(
        f"/sessions/{session.id}/files", cookies=auth_cookie(user_b)
    )
    assert attacker.status_code == 404


# ---------------------------------------------------------------------------
# GET /files/{id}/download
# ---------------------------------------------------------------------------


async def _seed_ready_file(
    db: AsyncSession, user: User, session: ThesisSession, r2_key: str
) -> File:
    file_row = File(
        session_id=session.id,
        user_id=user.id,
        filename="Test_MA_Dissertation.docx",
        file_type="docx",
        r2_key=r2_key,
        status="ready",
        size_bytes=1,
    )
    db.add(file_row)
    await db.commit()
    await db.refresh(file_row)
    return file_row


async def test_download_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """User B must not be able to download User A's file."""
    session = await _seed_session_with_reply(db_session, user_a)
    file_row = await _seed_ready_file(db_session, user_a, session, "files/a/b/c.docx")

    response = await client.get(
        f"/files/{file_row.id}/download", cookies=auth_cookie(user_b)
    )
    assert response.status_code == 404


async def test_download_not_ready_returns_409(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A file still compiling (or failed) cannot be downloaded."""
    session = await _seed_session_with_reply(db_session, user_a)
    file_row = File(
        session_id=session.id,
        user_id=user_a.id,
        filename="pending.docx",
        file_type="docx",
        r2_key=None,
        status="compiling",
    )
    db_session.add(file_row)
    await db_session.commit()
    await db_session.refresh(file_row)

    response = await client.get(
        f"/files/{file_row.id}/download", cookies=auth_cookie(user_a)
    )
    assert response.status_code == 409


async def test_download_ready_local_backend_serves_docx(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the local backend, the route serves the bytes with the docx type."""
    from app.services.storage_service import LocalStorageService

    settings_obj = __import__(
        "app.core.config", fromlist=["get_settings"]
    ).get_settings()
    monkeypatch.setattr(settings_obj, "LOCAL_STORAGE_DIR", str(tmp_path))
    storage = LocalStorageService()

    key = f"files/{user_a.id}/test/{uuid4()}.docx"
    src = tmp_path / "src.docx"
    src.write_bytes(b"PK\x03\x04 not a real docx but bytes suffice")
    await storage.upload_file(str(src), key)

    monkeypatch.setattr("app.api.compile.get_storage_service", lambda: storage)

    session = await _seed_session_with_reply(db_session, user_a)
    file_row = await _seed_ready_file(db_session, user_a, session, key)

    response = await client.get(
        f"/files/{file_row.id}/download", cookies=auth_cookie(user_a)
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == DOCX_MEDIA_TYPE
    assert "attachment" in response.headers.get("content-disposition", "")
    assert response.content.startswith(b"PK\x03\x04")


# ---------------------------------------------------------------------------
# run_compile background job (real formatter, mocked Claude, local storage)
# ---------------------------------------------------------------------------


async def test_run_compile_end_to_end(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The background job renders a real .docx via the locked formatter and
    flips the File row to 'ready'.

    Seeds its own committed rows (run_compile opens its own DB session, so
    savepoint-scoped fixtures are invisible to it) and cleans up afterward.
    """
    from app.core.config import get_settings
    from app.db.session import AsyncSessionLocal, engine
    from app.services.compile_service import run_compile
    from app.services.storage_service import LocalStorageService

    settings_obj = get_settings()
    monkeypatch.setattr(settings_obj, "LOCAL_STORAGE_DIR", str(tmp_path))
    storage = LocalStorageService()
    monkeypatch.setattr(
        "app.services.compile_service.get_storage_service", lambda: storage
    )

    class _StubClaude:
        async def call_compile(self, **kwargs) -> str:
            return MINIMAL_COMPILE_JSON

    monkeypatch.setattr(
        "app.services.compile_service.get_claude_service", lambda: _StubClaude()
    )

    inst_id = user_id = session_id = file_id = None
    async with AsyncSessionLocal() as db:
        inst = Institution(
            name="Compile Test College",
            short_name=f"CT{uuid4().hex[:6]}",
            email_domains="compile-test.edu",
            address="1 Compile Street, Testville – 600 000.",
            short_address="Testville",
            university_name="Test University",
            default_department="Department of English",
            department_aided=False,
        )
        db.add(inst)
        await db.commit()
        await db.refresh(inst)
        inst_id = inst.id

        user = User(
            email=f"compile-{uuid4().hex[:8]}@compile-test.edu",
            full_name="Carol Compile",
            register_number="REG123",
            institution_id=inst.id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id

        session = ThesisSession(
            user_id=user.id,
            title="Identity and Empire in Things Fall Apart",
            supervisor_full_name="Dr. S. Supervisor",
            supervisor_designation="Associate Professor",
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id

        db.add_all(
            [
                Message(
                    session_id=session.id, role=ROLE_USER, content="Guide me."
                ),
                Message(
                    session_id=session.id,
                    role=ROLE_ASSISTANT,
                    content="We have discussed your chapters in depth.",
                ),
            ]
        )
        file_row = File(
            session_id=session.id,
            user_id=user.id,
            filename="Compile_MA_Dissertation.docx",
            file_type="docx",
            r2_key=None,
            status="compiling",
        )
        db.add(file_row)
        await db.commit()
        await db.refresh(file_row)
        file_id = file_row.id

    try:
        await run_compile(file_id, session_id, user_id)

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(File).where(File.id == file_id))
            refreshed = result.scalar_one()
            assert refreshed.status == "ready", (
                f"expected ready, got {refreshed.status!r} "
                f"(error: {refreshed.error_message!r})"
            )
            assert refreshed.r2_key == f"files/{user_id}/{session_id}/{file_id}.docx"
            assert refreshed.size_bytes and refreshed.size_bytes > 0

            docx_path = await storage.open_local_path(refreshed.r2_key)
            doc = Document(docx_path)
            all_text = "\n".join(p.text for p in doc.paragraphs)
            assert "INTRODUCTION" in all_text
            assert "colonial encounter" in all_text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Message).where(Message.session_id == session_id))
            await db.execute(delete(File).where(File.id == file_id))
            await db.execute(
                delete(ThesisSession).where(ThesisSession.id == session_id)
            )
            await db.execute(delete(User).where(User.id == user_id))
            await db.execute(delete(Institution).where(Institution.id == inst_id))
            await db.commit()
        # The module-level engine pooled connections on this test's event loop;
        # dispose them so later tests (other loops) can't pick them up.
        await engine.dispose()


async def test_concurrent_compiling_rows_rejected_by_index(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """The partial unique index allows only one 'compiling' file per session.

    This is the DB-level backstop for the route's 409 guard (TOCTOU race).
    """
    from sqlalchemy.exc import IntegrityError

    session = await _seed_session_with_reply(db_session, user_a)
    # Plain values: rollback() below expires ORM instances, and attribute
    # access on expired objects triggers sync lazy-refresh (MissingGreenlet).
    session_id, user_id = session.id, user_a.id
    db_session.add(
        File(
            session_id=session_id,
            user_id=user_id,
            filename="first.docx",
            file_type="docx",
            status="compiling",
        )
    )
    await db_session.commit()

    db_session.add(
        File(
            session_id=session_id,
            user_id=user_id,
            filename="second.docx",
            file_type="docx",
            status="compiling",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

    # A second 'ready' or 'failed' file is still fine.
    db_session.add(
        File(
            session_id=session_id,
            user_id=user_id,
            filename="done.docx",
            file_type="docx",
            r2_key="files/x/y/done.docx",
            status="ready",
        )
    )
    await db_session.commit()
