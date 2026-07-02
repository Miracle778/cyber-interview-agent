import asyncio
import time
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cyber_interview.domain.constants import DEFAULT_WORKSPACE_ID
from cyber_interview.infra.db import engine_from_settings
from cyber_interview.infra.models import AgentRunRow, Base, RunEventRow
from cyber_interview.infra.repositories import (
    ArtifactRepository,
    ArtifactVersionRepository,
    RunEventRepository,
)


@pytest.fixture
async def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("CIA_DATA_DIR", str(tmp_path))
    from cyber_interview.settings import get_settings

    get_settings.cache_clear()
    eng = engine_from_settings(get_settings())
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.mark.asyncio
async def test_terminal_event_unique(engine):
    async with AsyncSession(engine, expire_on_commit=False) as s:
        runs = list((await s.execute(select(AgentRunRow))).scalars())
    for run in runs:
        async with AsyncSession(engine, expire_on_commit=False) as s:
            events = list(
                (await s.execute(select(RunEventRow).where(RunEventRow.run_id == run.id))).scalars()
            )
            terminals = [event for event in events if event.event_type in ("completed", "failed")]
            assert len(terminals) == 1


@pytest.mark.asyncio
async def test_sse_replay_exclusive(engine):
    async with AsyncSession(engine, expire_on_commit=False) as s:
        artifact = await ArtifactRepository(s).get_or_create_profile()
        run = AgentRunRow(
            id=str(uuid.uuid4()),
            artifact_id=artifact.id,
            workspace_id=DEFAULT_WORKSPACE_ID,
            status="completed",
            input_text="t",
            created_at=int(time.time()),
        )
        s.add(run)
        await s.flush()
        repo = RunEventRepository(s)
        await repo.append(run.id, "delta", {"text": "a"})
        await repo.append(run.id, "delta", {"text": "b"})
        await repo.append(run.id, "completed", {})
        await s.commit()
        run_id = run.id
    async with AsyncSession(engine, expire_on_commit=False) as s:
        after1 = await RunEventRepository(s).events_after(run_id, 0)
        after2 = await RunEventRepository(s).events_after(run_id, 1)
    assert len(after1) == 3
    assert len(after2) == 2 and after2[0].sequence == 2


@pytest.mark.asyncio
async def test_concurrent_version_allocation(engine):
    async with AsyncSession(engine, expire_on_commit=False) as s:
        artifact = await ArtifactRepository(s).get_or_create_profile()
        await s.commit()
        artifact_id = artifact.id

    async def make_version():
        async with AsyncSession(engine, expire_on_commit=False) as s:
            await s.execute(text("BEGIN IMMEDIATE"))
            vrepo = ArtifactVersionRepository(s)
            version_no = await vrepo.next_version_no(artifact_id)
            version = await vrepo.create_draft(artifact_id, version_no, "{}")
            await vrepo.set_status(version.id, "pending_approval")
            await s.commit()
            return version.version_no

    numbers = await asyncio.gather(make_version(), make_version())
    assert numbers[0] != numbers[1]
