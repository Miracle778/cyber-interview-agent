from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cyber_interview.domain.artifact import ArtifactStatus
from cyber_interview.infra.models import ArtifactVersionRow
from cyber_interview.infra.repositories import ArtifactRepository, ArtifactVersionRepository

SessionFactory = Callable[[], AsyncSession]


class AlreadyPublishedError(Exception):
    pass


class ArtifactApprovalService:
    def __init__(self, session_factory: SessionFactory):
        self._sf = session_factory

    async def approve(self, version_id: str) -> None:
        async with self._sf() as s:
            await s.execute(text("BEGIN IMMEDIATE"))
            version = await s.get(ArtifactVersionRow, version_id)
            if version is None:
                await s.rollback()
                raise ValueError("version not found")
            if version.status != ArtifactStatus.PENDING_APPROVAL.value:
                await s.rollback()
                raise ValueError(f"cannot approve from {version.status}")
            if await ArtifactRepository(s).has_published(version.artifact_id):
                await s.rollback()
                raise AlreadyPublishedError("artifact already has a published version")
            try:
                await ArtifactVersionRepository(s).set_status(
                    version_id, ArtifactStatus.PUBLISHED.value
                )
                await s.commit()
            except IntegrityError as exc:
                await s.rollback()
                raise AlreadyPublishedError("artifact already has a published version") from exc
