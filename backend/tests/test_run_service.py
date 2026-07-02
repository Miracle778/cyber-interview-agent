import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cyber_interview.app.run_service import AgentRunService
from cyber_interview.harness.fake_model import FakeModelGateway
from cyber_interview.harness.model_gateway import ModelChunk
from cyber_interview.harness.runtime import LoopAgentRuntime
from cyber_interview.harness.task_registry import TaskRegistry
from cyber_interview.infra.db import engine_from_settings
from cyber_interview.infra.models import AgentRunRow, ArtifactVersionRow, RunAttemptRow, RunEventRow


@pytest.fixture
async def services(tmp_path, monkeypatch):
    monkeypatch.setenv("CIA_DATA_DIR", str(tmp_path))
    from cyber_interview.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    engine = engine_from_settings(settings)
    async with engine.begin() as conn:
        from cyber_interview.infra.models import Base

        await conn.run_sync(Base.metadata.create_all)

    def factory():
        return AsyncSession(engine, expire_on_commit=False)

    payload = json.dumps(
        {
            "schema_name": "profile",
            "schema_version": 1,
            "facts": [{"claim": "x", "evidence_ref": None}],
        }
    )
    gw = FakeModelGateway(
        chunks=[
            ModelChunk(type="delta", text=payload),
            ModelChunk(type="done", finish_reason="stop"),
        ]
    )
    runtime = LoopAgentRuntime(model_gateway=gw)
    registry = TaskRegistry()
    service = AgentRunService(session_factory=factory, runtime=runtime, registry=registry)
    yield service, engine
    await registry.shutdown()
    await engine.dispose()


@pytest.mark.asyncio
async def test_success_path_creates_pending_approval_and_completed_event(services):
    service, engine = services
    artifact_id = await service._ensure_artifact()
    run_id = await service.create_run(artifact_id=artifact_id, input_text="some text")
    await service._await_completion(run_id)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        run = (await s.execute(select(AgentRunRow).where(AgentRunRow.id == run_id))).scalar_one()
        assert run.status == "completed"
        attempt = (
            await s.execute(select(RunAttemptRow).where(RunAttemptRow.run_id == run_id))
        ).scalar_one()
        assert attempt.status == "completed" and attempt.ended_at is not None
        events = list(
            (
                await s.execute(
                    select(RunEventRow)
                    .where(RunEventRow.run_id == run_id)
                    .order_by(RunEventRow.sequence)
                )
            ).scalars()
        )
        types = [e.event_type for e in events]
        assert types.count("completed") == 1
        assert types[-1] == "completed"
        versions = list(
            (
                await s.execute(
                    select(ArtifactVersionRow).where(ArtifactVersionRow.artifact_id == artifact_id)
                )
            ).scalars()
        )
        assert any(v.status == "pending_approval" for v in versions)


@pytest.mark.asyncio
async def test_failure_path_writes_failed_event_and_attempt_ended(services):
    service, engine = services
    gw_bad = FakeModelGateway(
        chunks=[
            ModelChunk(type="delta", text="not json"),
            ModelChunk(type="done", finish_reason="stop"),
        ]
    )
    service._runtime = LoopAgentRuntime(model_gateway=gw_bad)
    artifact_id = await service._ensure_artifact()
    run_id = await service.create_run(artifact_id=artifact_id, input_text="some text")
    await service._await_completion(run_id)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        run = (await s.execute(select(AgentRunRow).where(AgentRunRow.id == run_id))).scalar_one()
        assert run.status == "failed"
        attempt = (
            await s.execute(select(RunAttemptRow).where(RunAttemptRow.run_id == run_id))
        ).scalar_one()
        assert attempt.status == "failed" and attempt.ended_at is not None
        events = list(
            (
                await s.execute(
                    select(RunEventRow)
                    .where(RunEventRow.run_id == run_id)
                    .order_by(RunEventRow.sequence)
                )
            ).scalars()
        )
        assert events[-1].event_type == "failed"
