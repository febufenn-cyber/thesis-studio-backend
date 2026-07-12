"""Regression test for the optimistic-concurrency lost-update race.

Two interleaved saves that share the same base document version must yield
exactly one 200 and one 409. Before the row-lock gate in
``editor_service._apply`` both could return 200 and the second commit silently
overwrote the first (found by scripts/run_local_perf.py on 2026-07-12).

This test drives the app's real ``get_db`` sessions with real commits — the
conftest savepoint session cannot express two competing transactions — so it
seeds and removes its own rows.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.canonical.model import ChapterDoc, ParagraphBlock, Run, ThesisDocument
from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal, engine
from app.main import app
from app.models.document_command import DocumentCommand
from app.models.document_snapshot import DocumentSnapshot
from app.models.event import Event
from app.models.institution import Institution
from app.models.project import Project
from app.models.user import User


async def _seed() -> tuple[UUID, UUID, UUID, UUID, str]:
    """Create institution, user and a small project with real commits."""
    document = ThesisDocument(
        chapters=[
            ChapterDoc(
                number=1,
                title="Concurrency",
                blocks=[
                    ParagraphBlock(runs=[Run(text=f"Synthetic paragraph {i}.")])
                    for i in range(10)
                ],
            )
        ]
    )
    payload = document.model_dump(mode="json")
    block_id = payload["chapters"][0]["blocks"][5]["id"]
    async with AsyncSessionLocal() as db:
        inst = Institution(
            name="Concurrency Test University",
            short_name="CT",
            email_domains="concurrency.test",
            address="1 Race Road",
            short_address="Racetown",
            university_name="Concurrency Test University",
            default_department="Department of English",
            department_aided=False,
        )
        db.add(inst)
        await db.flush()
        user = User(
            email=f"race-{uuid4().hex[:10]}@concurrency.test",
            full_name="Race Probe",
            institution_id=inst.id,
        )
        db.add(user)
        await db.flush()
        project = Project(
            user_id=user.id,
            title="Lost-update regression",
            mode="operator",
            doc_type="ma_dissertation",
            format_profile="tn_university",
            document_version=1,
            canonical_schema_version=payload["schema_version"],
            chapters=payload["chapters"],
        )
        db.add(project)
        await db.commit()
        return inst.id, user.id, project.id, UUID(block_id), create_access_token(user.id)


async def _cleanup(inst_id: UUID, user_id: UUID, project_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        for model in (DocumentCommand, DocumentSnapshot, Event):
            await db.execute(delete(model).where(model.project_id == project_id))
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.execute(delete(Institution).where(Institution.id == inst_id))
        await db.commit()


async def test_interleaved_same_version_saves_yield_exactly_one_winner() -> None:
    inst_id, user_id, project_id, block_id, token = await _seed()
    try:
        transport = ASGITransport(app=app)

        async def save(tag: str) -> int:
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                cookies={"access_token": token},
            ) as client:
                response = await client.post(
                    f"/projects/{project_id}/editor/commands",
                    json={
                        "command_type": "update_block_text",
                        "payload": {
                            "block_id": str(block_id),
                            "runs": [{"text": f"Probe {tag} from base version 1."}],
                        },
                        "expected_document_version": 1,
                    },
                )
                return response.status_code

    # Both requests carry the same base version and run concurrently through
    # independent database transactions: exactly one may win.
        statuses = sorted(await asyncio.gather(save("a"), save("b")))
        assert statuses == [200, 409], (
            f"lost-update invariant violated: got {statuses}; two 200s mean the "
            "second commit silently overwrote the first"
        )
    finally:
        await _cleanup(inst_id, user_id, project_id)
        # Connections created here are bound to this test's event loop; leaving
        # them pooled poisons later tests that reuse the app's global engine.
        await engine.dispose()
