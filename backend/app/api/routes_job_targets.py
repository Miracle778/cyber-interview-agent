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
    AnalysisControlCommand,
    JobAnalysisStartCommand,
    ProjectDeepDiveStartCommand,
    DeepDiveAnswerCommand,
    MessageResolutionCommand,
    QuestionCandidateDecisionCommand,
    NarrativeDecisionCommand,
    GapDispatchCommand,
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


@router.post("/api/job-targets/{target_id}/analysis-runs", status_code=202)
async def start_analysis(target_id: str, command: JobAnalysisStartCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    service = _service(application, command.workspace_id)
    if service.get_target(target_id).version != command.expected_version:
        raise JobTargetNotFound(target_id)
    return await application.job_training(command.workspace_id).start_analysis(target_id)


@router.get("/api/job-targets/{target_id}/analysis-runs/current")
def current_analysis(target_id: str, workspace_id: Annotated[str, Query(alias="workspaceId")], application: AgentApplication = Depends(get_agent_application)):
    return application.job_training(workspace_id).current_analysis(target_id)


async def _analysis_control(target_id, run_id, command, application, action):
    _service(application, command.workspace_id).get_target(target_id)
    return await application.job_training(command.workspace_id).control_analysis(run_id, action)


@router.post("/api/job-targets/{target_id}/analysis-runs/{run_id}/pause")
async def pause_analysis(target_id: str, run_id: str, command: AnalysisControlCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return await _analysis_control(target_id, run_id, command, application, "pause")


@router.post("/api/job-targets/{target_id}/analysis-runs/{run_id}/resume")
async def resume_analysis(target_id: str, run_id: str, command: AnalysisControlCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return await _analysis_control(target_id, run_id, command, application, "resume")


@router.post("/api/job-targets/{target_id}/analysis-runs/{run_id}/terminate")
async def terminate_analysis(target_id: str, run_id: str, command: AnalysisControlCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return await _analysis_control(target_id, run_id, command, application, "terminate")


@router.post("/api/job-targets/{target_id}/analysis-runs/{run_id}/work-items/{item_id}/retry")
async def retry_work_item(target_id: str, run_id: str, item_id: str, command: AnalysisControlCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    _service(application, command.workspace_id).get_target(target_id)
    return await application.job_training(command.workspace_id).retry_work_item(run_id, item_id)


@router.get("/api/job-targets/{target_id}/readiness")
def target_readiness(target_id: str, workspace_id: Annotated[str, Query(alias="workspaceId")], application: AgentApplication = Depends(get_agent_application)):
    return application.job_training(workspace_id).readiness(target_id)


@router.post("/api/job-targets/{target_id}/projects/{project_id}/deep-dives", status_code=201)
async def create_deep_dive(target_id: str, project_id: str, command: ProjectDeepDiveStartCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    if command.project_claim_id != project_id:
        raise JobTargetNotFound(project_id)
    return await application.job_training(command.workspace_id).create_deep_dive(target_id, project_id)


@router.get("/api/job-targets/{target_id}/projects/{project_id}/deep-dives/current")
def current_deep_dive(target_id: str, project_id: str, workspace_id: Annotated[str, Query(alias="workspaceId")], application: AgentApplication = Depends(get_agent_application)):
    return application.job_training(workspace_id).current_deep_dive(target_id, project_id)


@router.post("/api/job-targets/{target_id}/deep-dives/{dive_id}/messages")
async def answer_deep_dive(target_id: str, dive_id: str, command: DeepDiveAnswerCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    _service(application, command.workspace_id).get_target(target_id)
    return await application.job_training(command.workspace_id).answer_deep_dive(
        dive_id,
        command.content,
        message_id=command.message_id,
        provider_model_id=command.provider_model_id,
        reasoning_effort=command.reasoning_effort,
    )


@router.post("/api/job-targets/{target_id}/deep-dives/{dive_id}/executions/{execution_id}/cancel")
async def cancel_deep_dive_execution(target_id: str, dive_id: str, execution_id: str, command: AnalysisControlCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    _service(application, command.workspace_id).get_target(target_id)
    return await application.job_training(command.workspace_id).cancel_deep_dive_execution(
        dive_id, execution_id
    )


@router.post("/api/job-targets/{target_id}/deep-dives/{dive_id}/executions/{execution_id}/retry")
async def retry_deep_dive(target_id: str, dive_id: str, execution_id: str, command: AnalysisControlCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    _service(application, command.workspace_id).get_target(target_id)
    return await application.job_training(command.workspace_id).retry_deep_dive(dive_id, execution_id)


@router.post("/api/job-targets/{target_id}/deep-dives/{dive_id}/messages/{message_id}/resolve")
def resolve_deep_dive_message(target_id: str, dive_id: str, message_id: str, command: MessageResolutionCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    _service(application, command.workspace_id).get_target(target_id)
    return application.job_training(command.workspace_id).resolve_message(dive_id, message_id, resolution=command.resolution, replacement=command.replacement_content)


async def _deep_dive_control(target_id, dive_id, command, application, action):
    _service(application, command.workspace_id).get_target(target_id)
    return await application.job_training(command.workspace_id).control_deep_dive(dive_id, action)


@router.post("/api/job-targets/{target_id}/deep-dives/{dive_id}/pause")
async def pause_deep_dive(target_id: str, dive_id: str, command: AnalysisControlCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return await _deep_dive_control(target_id, dive_id, command, application, "pause")


@router.post("/api/job-targets/{target_id}/deep-dives/{dive_id}/resume")
async def resume_deep_dive(target_id: str, dive_id: str, command: AnalysisControlCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return await _deep_dive_control(target_id, dive_id, command, application, "resume")


@router.post("/api/job-targets/{target_id}/deep-dives/{dive_id}/terminate")
async def terminate_deep_dive(target_id: str, dive_id: str, command: AnalysisControlCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    return await _deep_dive_control(target_id, dive_id, command, application, "terminate")


@router.post("/api/job-targets/{target_id}/deep-dives/{dive_id}/restart", status_code=201)
async def restart_deep_dive(target_id: str, dive_id: str, command: AnalysisControlCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    _service(application, command.workspace_id).get_target(target_id)
    return await application.job_training(command.workspace_id).restart_deep_dive(dive_id)


@router.post("/api/job-targets/{target_id}/question-candidates/{candidate_id}/decision", status_code=204)
def decide_project_question(target_id: str, candidate_id: str, command: QuestionCandidateDecisionCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    _service(application, command.workspace_id).get_target(target_id)
    application.job_training(command.workspace_id).decide_question_candidate(candidate_id, command.decision)
    return Response(status_code=204)


@router.post("/api/job-targets/{target_id}/narrative-artifacts/{artifact_id}/confirm")
def confirm_narrative(target_id: str, artifact_id: str, command: NarrativeDecisionCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    _service(application, command.workspace_id).get_target(target_id)
    return application.job_training(command.workspace_id).confirm_narrative_sections(
        artifact_id,
        section_ids=tuple(command.section_ids),
        edited_values=command.edited_values,
        expected_project_version=command.expected_project_version,
        idempotency_key=idempotency_key,
    )


@router.post("/api/job-targets/{target_id}/gaps/{gap_id}/dispatch")
def dispatch_gap(target_id: str, gap_id: str, command: GapDispatchCommand, idempotency_key: IdempotencyKey, application: AgentApplication = Depends(get_agent_application)):
    _service(application, command.workspace_id).get_target(target_id)
    return application.job_training(command.workspace_id).dispatch_gap(
        gap_id, idempotency_key=idempotency_key
    )
