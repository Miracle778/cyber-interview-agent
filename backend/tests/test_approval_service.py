import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cyber_interview.app.approval_service import AlreadyPublishedError, ArtifactApprovalService
from cyber_interview.infra.db import engine_from_settings
from cyber_interview.infra.models import ArtifactVersionRow, Base
from cyber_interview.infra.repositories import ArtifactRepository, ArtifactVersionRepository


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
async def test_approve_transitions_to_published(engine):
    async with AsyncSession(engine, expire_on_commit=False) as s:
        artifact = await ArtifactRepository(s).get_or_create_profile()
        vrepo = ArtifactVersionRepository(s)
        v = await vrepo.create_draft(artifact.id, await vrepo.next_version_no(artifact.id), "{}")
        await vrepo.set_status(v.id, "pending_approval")
        await s.commit()
        version_id = v.id

    def session_factory():
        return AsyncSession(engine, expire_on_commit=False)

    svc = ArtifactApprovalService(session_factory=session_factory)
    await svc.approve(version_id)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        v = await s.get(ArtifactVersionRow, version_id)
        assert v.status == "published" and v.published_at is not None


@pytest.mark.asyncio
async def test_second_publish_rejected(engine):
    async with AsyncSession(engine, expire_on_commit=False) as s:
        artifact = await ArtifactRepository(s).get_or_create_profile()
        vrepo = ArtifactVersionRepository(s)
        v1 = await vrepo.create_draft(artifact.id, 1, "{}")
        v2 = await vrepo.create_draft(artifact.id, 2, "{}")
        await vrepo.set_status(v1.id, "pending_approval")
        await vrepo.set_status(v2.id, "pending_approval")
        await s.commit()
        id1, id2 = v1.id, v2.id

    def session_factory():
        return AsyncSession(engine, expire_on_commit=False)

    svc = ArtifactApprovalService(session_factory=session_factory)
    await svc.approve(id1)
    with pytest.raises(AlreadyPublishedError):
        await svc.approve(id2)


@pytest.mark.asyncio
async def test_concurrent_approve_only_one_published(engine):
    async with AsyncSession(engine, expire_on_commit=False) as s:
        artifact = await ArtifactRepository(s).get_or_create_profile()
        vrepo = ArtifactVersionRepository(s)
        v1 = await vrepo.create_draft(artifact.id, 1, "{}")
        v2 = await vrepo.create_draft(artifact.id, 2, "{}")
        await vrepo.set_status(v1.id, "pending_approval")
        await vrepo.set_status(v2.id, "pending_approval")
        await s.commit()
        id1, id2 = v1.id, v2.id

    def session_factory():
        return AsyncSession(engine, expire_on_commit=False)

    svc = ArtifactApprovalService(session_factory=session_factory)
    await asyncio.gather(svc.approve(id1), svc.approve(id2), return_exceptions=True)
    published_count = 0
    async with AsyncSession(engine, expire_on_commit=False) as s:
        for vid in (id1, id2):
            v = await s.get(ArtifactVersionRow, vid)
            if v.status == "published":
                published_count += 1
    assert published_count == 1
