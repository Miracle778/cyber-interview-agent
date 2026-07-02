import pytest
from alembic.config import Config
from sqlalchemy import inspect

from alembic import command
from cyber_interview.infra.db import engine_from_settings


@pytest.fixture
async def applied_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("CIA_DATA_DIR", str(tmp_path))
    from cyber_interview.settings import get_settings

    get_settings.cache_clear()
    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")
    engine = engine_from_settings(get_settings())
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_tables_created(applied_engine):
    async with applied_engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
    assert {
        "artifact",
        "artifact_version",
        "agent_run",
        "run_attempt",
        "run_event",
        "model_call",
    } <= tables


@pytest.mark.asyncio
async def test_partial_unique_index_exists(applied_engine):
    async with applied_engine.connect() as conn:
        indexes = await conn.run_sync(
            lambda sync_conn: {
                i["name"] for i in inspect(sync_conn).get_indexes("artifact_version")
            }
        )
    assert "uq_artifact_one_published" in indexes
