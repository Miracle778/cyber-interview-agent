import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine

from cyber_interview.infra.db import engine_from_settings, session_factory_from_settings


def test_engine_from_settings_returns_async_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("CIA_DATA_DIR", str(tmp_path))
    from cyber_interview.settings import get_settings

    get_settings.cache_clear()
    engine = engine_from_settings(get_settings())
    assert isinstance(engine, AsyncEngine)
    asyncio.run(engine.dispose())


def test_session_factory_returns_sessionmaker(tmp_path, monkeypatch):
    monkeypatch.setenv("CIA_DATA_DIR", str(tmp_path))
    from cyber_interview.settings import get_settings

    get_settings.cache_clear()
    factory = session_factory_from_settings(get_settings())
    assert factory is not None
