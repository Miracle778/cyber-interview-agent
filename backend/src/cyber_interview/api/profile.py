import asyncio
import json

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

try:
    from sse_starlette.sse import EventSourceResponse
except ModuleNotFoundError:

    class EventSourceResponse(StreamingResponse):
        def __init__(self, content, ping: int = 15):
            super().__init__(content, media_type="text/event-stream")


from cyber_interview.api.errors import ErrorEnvelope, ErrorResponse
from cyber_interview.app.approval_service import AlreadyPublishedError
from cyber_interview.domain.errors import ErrorCategory
from cyber_interview.infra.models import AgentRunRow, ArtifactVersionRow
from cyber_interview.infra.repositories import RunEventRepository

router = APIRouter(prefix="/api/profile")


class CreateRunBody(BaseModel):
    text: str


class CreateRunResponse(BaseModel):
    run_id: str


def _get_services(request: Request):
    return (
        request.app.state.profile_service,
        request.app.state.approval_service,
        request.app.state.session_factory,
    )


@router.post("/runs", response_model=CreateRunResponse)
async def create_run(body: CreateRunBody, request: Request) -> CreateRunResponse:
    profile_svc, _, _ = _get_services(request)
    run_id = await profile_svc.create_run(input_text=body.text)
    return CreateRunResponse(run_id=run_id)


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> dict:
    _, _, sf = _get_services(request)
    async with sf() as s:
        run = await s.get(AgentRunRow, run_id)
        if run is None:
            raise _not_found("run_not_found", "run not found")
        stmt = (
            select(ArtifactVersionRow)
            .where(
                ArtifactVersionRow.artifact_id == run.artifact_id,
                ArtifactVersionRow.status == "pending_approval",
            )
            .order_by(ArtifactVersionRow.version_no.desc())
        )
        version = (await s.execute(stmt)).scalars().first()
        return {
            "run_id": run.id,
            "status": run.status,
            "pending_version": (
                {"id": version.id, "content": json.loads(version.content_json)} if version else None
            ),
        }


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    _, _, sf = _get_services(request)
    async with sf() as s:
        run = await s.get(AgentRunRow, run_id)
        if run is None:
            raise _not_found("run_not_found", "run not found")

    last_seq = int(last_event_id) if last_event_id else 0

    async def event_gen():
        current_seq = last_seq
        terminal_seen = False
        while True:
            async with sf() as s:
                events = await RunEventRepository(s).events_after(run_id, current_seq)
            for event in events:
                payload = json.loads(event.payload_json)
                data = json.dumps(
                    {
                        "run_id": run_id,
                        "sequence": event.sequence,
                        "event_type": event.event_type,
                        "payload": payload,
                        "created_at": event.created_at,
                    }
                )
                yield {"id": str(event.sequence), "event": event.event_type, "data": data}
                current_seq = event.sequence
                if event.event_type in ("completed", "failed"):
                    terminal_seen = True
            if terminal_seen:
                break
            await asyncio.sleep(0.1)

    return EventSourceResponse(event_gen(), ping=15)


@router.post("/artifact-versions/{version_id}/approve")
async def approve_version(version_id: str, request: Request) -> dict:
    _, approval_svc, sf = _get_services(request)
    async with sf() as s:
        version = await s.get(ArtifactVersionRow, version_id)
        if version is None:
            raise _not_found("version_not_found", "version not found")
    try:
        await approval_svc.approve(version_id)
    except AlreadyPublishedError as exc:
        env = ErrorEnvelope(
            code="already_published",
            category=ErrorCategory.POLICY,
            retryable=False,
            safe_message=str(exc),
            diagnostic_id=version_id,
            next_actions=[],
        )
        raise HTTPException(
            status_code=409, detail=ErrorResponse(envelope=env).model_dump()
        ) from exc
    return {"status": "published"}


def _not_found(code: str, message: str) -> HTTPException:
    env = ErrorEnvelope(
        code=code,
        category=ErrorCategory.INPUT,
        retryable=False,
        safe_message=message,
        diagnostic_id=code,
        next_actions=[],
    )
    return HTTPException(status_code=404, detail=ErrorResponse(envelope=env).model_dump())
