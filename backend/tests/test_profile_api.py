import pytest
from httpx import ASGITransport, AsyncClient

from cyber_interview.main import create_app


@pytest.fixture
async def app_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("CIA_DATA_DIR", str(tmp_path))
    from cyber_interview.settings import get_settings

    get_settings.cache_clear()
    from cyber_interview.infra.db import engine_from_settings
    from cyber_interview.infra.models import Base

    engine = engine_from_settings(get_settings())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    import cyber_interview.main as m

    m._reset_singletons()
    return create_app()


@pytest.mark.asyncio
async def test_create_run_returns_run_id(app_factory):
    transport = ASGITransport(app=app_factory)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/profile/runs", json={"text": "some text"})
        assert resp.status_code == 200
        assert "run_id" in resp.json()


@pytest.mark.asyncio
async def test_events_for_missing_run_returns_404(app_factory):
    transport = ASGITransport(app=app_factory)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/profile/runs/nonexistent/events")
        assert resp.status_code == 404
        body = resp.json()
        assert body["detail"]["envelope"]["code"] == "run_not_found"


@pytest.mark.asyncio
async def test_approve_missing_version_returns_404(app_factory):
    transport = ASGITransport(app=app_factory)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/api/profile/artifact-versions/nonexistent/approve")
        assert resp.status_code == 404
