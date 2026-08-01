from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.interview_retrospectives.projection import (
    cleanup_version_resource,
    retrospective_resource,
    source_version_resource,
)
from app.schemas.interview_retrospectives import (
    AddSourceVersionCommand,
    CleanupControlCommand,
    CleanupStartResource,
    CleanupVersionResource,
    CreateRetrospectiveCommand,
    DeleteRetrospectiveCommand,
    DeletionImpactResource,
    RetrospectiveResource,
    SourceVersionResource,
    StartCleanupCommand,
    UpdateRetrospectiveCommand,
    UpdateSegmentsCommand,
    VersionedRetrospectiveCommand,
)


router = APIRouter(tags=["interview-retrospectives"])
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
]


def _application(application: AgentApplication, workspace_id: str):
    return application.interview_retrospectives(workspace_id)


@router.get(
    "/api/interview-retrospectives", response_model=list[RetrospectiveResource]
)
def list_retrospectives(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    lifecycle_status: Annotated[
        str, Query(alias="lifecycleStatus")
    ] = "active",
    job_target_id: Annotated[
        str | None, Query(alias="jobTargetId")
    ] = None,
    application: AgentApplication = Depends(get_agent_application),
):
    records = _application(application, workspace_id).list_retrospectives(
        lifecycle_status=lifecycle_status,
        job_target_id=job_target_id,
    )
    return [retrospective_resource(item) for item in records]


@router.post(
    "/api/interview-retrospectives",
    response_model=RetrospectiveResource,
    status_code=status.HTTP_201_CREATED,
)
async def create_retrospective(
    command: CreateRetrospectiveCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    values = command.model_dump(exclude={"workspace_id"})
    record = await _application(
        application, command.workspace_id
    ).create_retrospective(**values, idempotency_key=idempotency_key)
    return retrospective_resource(record)


@router.get(
    "/api/interview-retrospectives/{retrospective_id}",
    response_model=RetrospectiveResource,
)
def get_retrospective(
    retrospective_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    record = _application(application, workspace_id).get_retrospective(
        retrospective_id
    )
    return retrospective_resource(record)


@router.patch(
    "/api/interview-retrospectives/{retrospective_id}",
    response_model=RetrospectiveResource,
)
def update_retrospective(
    retrospective_id: str,
    command: UpdateRetrospectiveCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    values = command.model_dump(exclude={"workspace_id"})
    record = _application(application, command.workspace_id).update_retrospective(
        retrospective_id, **values, idempotency_key=idempotency_key
    )
    return retrospective_resource(record)


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/sources",
    response_model=SourceVersionResource,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
def add_source(
    retrospective_id: str,
    command: AddSourceVersionCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    values = command.model_dump(exclude={"workspace_id"})
    record = _application(application, command.workspace_id).add_source_version(
        retrospective_id, **values, idempotency_key=idempotency_key
    )
    return source_version_resource(record, include_body=False)


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/sources/{version_id}",
    response_model=SourceVersionResource,
    response_model_exclude_none=True,
)
def get_source(
    retrospective_id: str,
    version_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    record = _application(application, workspace_id).get_source_version(
        retrospective_id, version_id
    )
    return source_version_resource(record, include_body=True)


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/cleanup-runs",
    response_model=CleanupStartResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_cleanup(
    retrospective_id: str,
    command: StartCleanupCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    return await _application(application, command.workspace_id).start_cleanup(
        retrospective_id,
        source_version_id=command.source_version_id,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/cleanup-runs/{cleanup_id}/stop",
    response_model=CleanupVersionResource,
)
async def stop_cleanup(
    retrospective_id: str,
    cleanup_id: str,
    command: CleanupControlCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    service = _application(application, command.workspace_id)
    await service.stop_cleanup(
        retrospective_id,
        cleanup_id,
        idempotency_key=idempotency_key,
    )
    return _cleanup_resource(service, retrospective_id, cleanup_id)


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/cleanup-runs/{cleanup_id}/resume",
    response_model=CleanupStartResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_cleanup(
    retrospective_id: str,
    cleanup_id: str,
    command: CleanupControlCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    return await _application(application, command.workspace_id).resume_cleanup(
        retrospective_id,
        cleanup_id,
        idempotency_key=idempotency_key,
    )


def _cleanup_resource(service, retrospective_id: str, cleanup_id: str):
    cleanup = service.get_cleanup(retrospective_id, cleanup_id)
    return cleanup_version_resource(
        cleanup,
        segments=service.list_segments(retrospective_id, cleanup_id),
    )


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/cleanup-runs/current",
    response_model=CleanupVersionResource | None,
)
def get_current_cleanup(
    retrospective_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    service = _application(application, workspace_id)
    cleanup = service.current_cleanup(retrospective_id)
    if cleanup is None:
        return None
    return cleanup_version_resource(
        cleanup,
        segments=service.list_segments(retrospective_id, cleanup.id),
    )


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/cleanup-runs/{cleanup_id}",
    response_model=CleanupVersionResource,
)
def get_cleanup(
    retrospective_id: str,
    cleanup_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    return _cleanup_resource(
        _application(application, workspace_id), retrospective_id, cleanup_id
    )


@router.patch(
    "/api/interview-retrospectives/{retrospective_id}/cleanup-runs/{cleanup_id}/segments",
    response_model=CleanupVersionResource,
)
def update_segments(
    retrospective_id: str,
    cleanup_id: str,
    command: UpdateSegmentsCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    del idempotency_key
    service = _application(application, command.workspace_id)
    service.replace_segments(
        retrospective_id,
        cleanup_id,
        expected_version=command.expected_version,
        segments=tuple(item.model_dump() for item in command.segments),
    )
    return _cleanup_resource(service, retrospective_id, cleanup_id)


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/cleanup-runs/{cleanup_id}/confirm",
    response_model=CleanupVersionResource,
)
def confirm_cleanup(
    retrospective_id: str,
    cleanup_id: str,
    command: VersionedRetrospectiveCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    service = _application(application, command.workspace_id)
    service.confirm_cleanup(
        retrospective_id,
        cleanup_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    return _cleanup_resource(service, retrospective_id, cleanup_id)


def _lifecycle(retrospective_id, command, idempotency_key, application, action):
    service = _application(application, command.workspace_id)
    record = getattr(service, action)(
        retrospective_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    return retrospective_resource(record)


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/archive",
    response_model=RetrospectiveResource,
)
def archive_retrospective(retrospective_id: str, command: VersionedRetrospectiveCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return _lifecycle(retrospective_id, command, idempotency_key, application, "archive")


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/recycle",
    response_model=RetrospectiveResource,
)
def recycle_retrospective(retrospective_id: str, command: VersionedRetrospectiveCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return _lifecycle(retrospective_id, command, idempotency_key, application, "recycle")


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/restore",
    response_model=RetrospectiveResource,
)
def restore_retrospective(retrospective_id: str, command: VersionedRetrospectiveCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return _lifecycle(retrospective_id, command, idempotency_key, application, "restore")


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/deletion-impact",
    response_model=DeletionImpactResource,
)
def deletion_impact(retrospective_id: str, workspace_id: Annotated[str, Query(alias="workspaceId")], application: AgentApplication = Depends(get_agent_application)):
    return _application(application, workspace_id).deletion_impact(retrospective_id)


@router.delete(
    "/api/interview-retrospectives/{retrospective_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_retrospective(retrospective_id: str, command: DeleteRetrospectiveCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    _application(application, command.workspace_id).delete_permanently(
        retrospective_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    return Response(status_code=204)
