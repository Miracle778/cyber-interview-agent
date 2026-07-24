from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.job_targets.errors import JobTargetNotFound
from app.schemas.job_targets import (
    ConfirmJobDocumentCommand,
    CreateJobTargetCommand,
    JobDocumentVersionCommand,
    JobDocumentVersionResource,
    JobRequirementResource,
    JobTargetDeleteCommand,
    JobTargetLifecycleCommand,
    JobTargetResource,
    ProjectPriorityCommand,
    ProjectPriorityResource,
    RequirementDecisionCommand,
    RequirementDecisionResource,
    SafeRequirementConfirmationCommand,
    TargetDeletionImpactResource,
    UpdateJobTargetCommand,
)

router = APIRouter(tags=["job-targets"])
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
]


def _service(application: AgentApplication, workspace_id: str):
    return application.job_targets(workspace_id)


@router.post("/api/workspaces/{workspace_id}/job-targets", response_model=JobTargetResource, status_code=201)
def create_target(workspace_id: str, command: CreateJobTargetCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return _service(application, workspace_id).create_target(**command.model_dump(), idempotency_key=idempotency_key)


@router.get("/api/workspaces/{workspace_id}/job-targets", response_model=list[JobTargetResource])
def list_targets(workspace_id: str, include_archived: Annotated[bool, Query(alias="includeArchived")] = False, recycled_only: Annotated[bool, Query(alias="recycledOnly")] = False, application: AgentApplication = Depends(get_agent_application)):
    return _service(application, workspace_id).list_targets(include_archived=include_archived, recycled_only=recycled_only)


@router.get("/api/job-targets/{target_id}", response_model=JobTargetResource)
def get_target(target_id: str, workspace_id: Annotated[str, Query(alias="workspaceId")], application: AgentApplication = Depends(get_agent_application)):
    return _service(application, workspace_id).get_target(target_id)


@router.patch("/api/job-targets/{target_id}", response_model=JobTargetResource)
def update_target(target_id: str, command: UpdateJobTargetCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    values = command.model_dump(exclude={"workspace_id"})
    return _service(application, command.workspace_id).update_target(target_id, **values, idempotency_key=idempotency_key)


@router.post("/api/job-targets/{target_id}/document-versions", response_model=JobDocumentVersionResource, status_code=201)
def create_document(target_id: str, command: JobDocumentVersionCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return _service(application, command.workspace_id).create_document_version(target_id, source_kind=command.source_kind, body=command.body, idempotency_key=idempotency_key)


@router.get("/api/job-targets/{target_id}/document-versions", response_model=list[JobDocumentVersionResource])
def list_documents(target_id: str, workspace_id: Annotated[str, Query(alias="workspaceId")], application: AgentApplication = Depends(get_agent_application)):
    return _service(application, workspace_id).list_document_versions(target_id)


@router.post("/api/job-targets/{target_id}/document-versions/{version_id}/confirm", response_model=JobTargetResource)
def confirm_document(target_id: str, version_id: str, command: ConfirmJobDocumentCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return _service(application, command.workspace_id).confirm_document_version(target_id, version_id, expected_version=command.expected_version, idempotency_key=idempotency_key)


def _lifecycle(target_id, command, idempotency_key, application, action):
    return getattr(_service(application, command.workspace_id), f"{action}_target")(target_id, expected_version=command.expected_version, idempotency_key=idempotency_key)


@router.post("/api/job-targets/{target_id}/archive", response_model=JobTargetResource)
def archive_target(target_id: str, command: JobTargetLifecycleCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return _lifecycle(target_id, command, idempotency_key, application, "archive")


@router.post("/api/job-targets/{target_id}/recycle", response_model=JobTargetResource)
def recycle_target(target_id: str, command: JobTargetLifecycleCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return _lifecycle(target_id, command, idempotency_key, application, "recycle")


@router.post("/api/job-targets/{target_id}/restore", response_model=JobTargetResource)
def restore_target(target_id: str, command: JobTargetLifecycleCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return _lifecycle(target_id, command, idempotency_key, application, "restore")


@router.get("/api/job-targets/{target_id}/requirements", response_model=list[JobRequirementResource])
def list_requirements(target_id: str, workspace_id: Annotated[str, Query(alias="workspaceId")], application: AgentApplication = Depends(get_agent_application)):
    return _service(application, workspace_id).list_requirements(target_id)


@router.post("/api/job-targets/{target_id}/requirements/confirm-safe", response_model=RequirementDecisionResource)
def confirm_safe(target_id: str, command: SafeRequirementConfirmationCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return _service(application, command.workspace_id).confirm_safe_requirements(target_id, document_version_id=command.document_version_id, idempotency_key=idempotency_key)


@router.post("/api/job-targets/{target_id}/requirements/decisions", response_model=RequirementDecisionResource)
def decide_requirements(target_id: str, command: RequirementDecisionCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    decisions = tuple(item.model_dump() for item in command.decisions)
    return _service(application, command.workspace_id).decide_requirements(target_id, decisions=decisions, idempotency_key=idempotency_key)


@router.put("/api/job-targets/{target_id}/project-priorities", response_model=ProjectPriorityResource)
def set_project_priorities(target_id: str, command: ProjectPriorityCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return _service(application, command.workspace_id).set_project_priorities(target_id, core_project_id=command.core_project_id, supplementary_project_ids=tuple(command.supplementary_project_ids), expected_version=command.expected_version, idempotency_key=idempotency_key)


@router.get("/api/job-targets/{target_id}/deletion-impact", response_model=TargetDeletionImpactResource)
def deletion_impact(target_id: str, workspace_id: Annotated[str, Query(alias="workspaceId")], application: AgentApplication = Depends(get_agent_application)):
    return _service(application, workspace_id).deletion_impact(target_id)


@router.delete("/api/job-targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_target(target_id: str, command: JobTargetDeleteCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    _service(application, command.workspace_id).delete_target(target_id, idempotency_key=idempotency_key)
    return Response(status_code=204)
