import json
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cyber_interview.domain.constants import DEFAULT_WORKSPACE_ID
from cyber_interview.infra.models import ArtifactRow, ArtifactVersionRow, RunEventRow


def _now() -> int:
    return int(time.time() * 1000)


def _uuid() -> str:
    return str(uuid.uuid4())


class ArtifactRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def get_or_create_profile(self, workspace_id: str = DEFAULT_WORKSPACE_ID) -> ArtifactRow:
        stmt = select(ArtifactRow).where(
            ArtifactRow.workspace_id == workspace_id,
            ArtifactRow.kind == "profile",
        )
        existing = (await self._s.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing
        row = ArtifactRow(id=_uuid(), workspace_id=workspace_id, kind="profile", created_at=_now())
        self._s.add(row)
        try:
            await self._s.flush()
            return row
        except Exception:
            await self._s.rollback()
            return (await self._s.execute(stmt)).scalar_one()

    async def has_published(self, artifact_id: str) -> bool:
        stmt = select(ArtifactVersionRow).where(
            ArtifactVersionRow.artifact_id == artifact_id,
            ArtifactVersionRow.status == "published",
        )
        return (await self._s.execute(stmt)).scalar_one_or_none() is not None


class ArtifactVersionRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def next_version_no(self, artifact_id: str) -> int:
        stmt = select(func.max(ArtifactVersionRow.version_no)).where(
            ArtifactVersionRow.artifact_id == artifact_id
        )
        current = (await self._s.execute(stmt)).scalar_one()
        return (current or 0) + 1

    async def create_draft(
        self, artifact_id: str, version_no: int, content_json: str
    ) -> ArtifactVersionRow:
        row = ArtifactVersionRow(
            id=_uuid(),
            artifact_id=artifact_id,
            version_no=version_no,
            schema_name="profile",
            schema_version=1,
            content_json=content_json,
            status="draft",
            created_at=_now(),
        )
        self._s.add(row)
        await self._s.flush()
        return row

    async def set_status(self, version_id: str, status: str) -> None:
        row = await self._s.get(ArtifactVersionRow, version_id)
        if row is None:
            raise ValueError("version not found")
        row.status = status
        if status == "published":
            row.published_at = _now()
        await self._s.flush()

    async def get(self, version_id: str) -> ArtifactVersionRow | None:
        return await self._s.get(ArtifactVersionRow, version_id)


class RunEventRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def append(self, run_id: str, event_type: str, payload: dict) -> RunEventRow:
        seq_stmt = select(func.max(RunEventRow.sequence)).where(RunEventRow.run_id == run_id)
        current = (await self._s.execute(seq_stmt)).scalar_one()
        seq = (current or 0) + 1
        row = RunEventRow(
            id=_uuid(),
            run_id=run_id,
            sequence=seq,
            event_type=event_type,
            payload_json=json.dumps(payload),
            created_at=_now(),
        )
        self._s.add(row)
        await self._s.flush()
        return row

    async def events_after(self, run_id: str, last_sequence: int) -> list[RunEventRow]:
        stmt = (
            select(RunEventRow)
            .where(RunEventRow.run_id == run_id, RunEventRow.sequence > last_sequence)
            .order_by(RunEventRow.sequence)
        )
        return list((await self._s.execute(stmt)).scalars())
