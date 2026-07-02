import time
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cyber_interview.domain.constants import DEFAULT_WORKSPACE_ID
from cyber_interview.infra.repositories import ArtifactRepository, RunEventRepository


@pytest.fixture
async def session(tmp_path, monkeypatch):
    monkeypatch.setenv("CIA_DATA_DIR", str(tmp_path))
    from cyber_interview.settings import get_settings

    get_settings.cache_clear()
    from cyber_interview.infra.db import engine_from_settings

    engine = engine_from_settings(get_settings())
    async with engine.begin() as conn:
        from cyber_interview.infra.models import Base

        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_or_create_artifact_idempotent(session: AsyncSession):
    repo = ArtifactRepository(session)
    a1 = await repo.get_or_create_profile(DEFAULT_WORKSPACE_ID)
    a2 = await repo.get_or_create_profile(DEFAULT_WORKSPACE_ID)
    await session.commit()
    assert a1.id == a2.id


@pytest.mark.asyncio
async def test_append_event_increments_sequence(session: AsyncSession):
    art_repo = ArtifactRepository(session)
    artifact = await art_repo.get_or_create_profile(DEFAULT_WORKSPACE_ID)
    from cyber_interview.domain.run import RunStatus
    from cyber_interview.infra.models import AgentRunRow

    run = AgentRunRow(
        id=str(uuid.uuid4()),
        artifact_id=artifact.id,
        workspace_id=DEFAULT_WORKSPACE_ID,
        status=RunStatus.QUEUED.value,
        input_text="t",
        created_at=int(time.time()),
    )
    session.add(run)
    await session.flush()
    ev_repo = RunEventRepository(session)
    e1 = await ev_repo.append(run.id, "delta", {"text": "a"})
    e2 = await ev_repo.append(run.id, "delta", {"text": "b"})
    await session.commit()
    assert e1.sequence == 1 and e2.sequence == 2
