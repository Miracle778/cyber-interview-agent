from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.interview_retrospectives.projection import (
    action_item_resource,
    analysis_run_resource,
    analysis_work_item_resource,
    asset_candidate_resource,
    cleanup_version_resource,
    question_analysis_resource,
    question_resource,
    retrospective_resource,
    source_version_resource,
)
from app.schemas.interview_retrospectives import (
    ActionDecisionCommand,
    ActionItemResource,
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
    UpdateCleanTranscriptCommand,
    UpdateSegmentsCommand,
    VersionedRetrospectiveCommand,
    AnalysisControlCommand,
    AnalysisReportResource,
    AnalysisRunResource,
    AnalysisStartResource,
    AssetCandidateResource,
    BatchCandidateDecisionCommand,
    BatchCandidateDecisionResult,
    CandidateDecisionCommand,
    ImmediatePracticeResource,
    PublicationDraftCommand,
    PublicationDraftResource,
    QuestionDecisionCommand,
    QuestionResource,
    RetrospectiveChatCommand,
    RetrospectiveChatControlCommand,
    CorrectionDecisionCommand,
    CorrectionProposalResource,
    RetrospectiveConversationResource,
    StartAnalysisCommand,
)


router = APIRouter(tags=["interview-retrospectives"])
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
]


def _application(application: AgentApplication, workspace_id: str):
    return application.interview_retrospectives(workspace_id)


def _retrospective_resource(service, record):
    source_available = False
    if record.active_source_version_id is not None:
        source = service.get_source_version(
            record.id, record.active_source_version_id
        )
        source_available = source.cleared_at is None
    return retrospective_resource(
        record, active_source_available=source_available
    )


@router.get("/api/interview-retrospectives", response_model=list[RetrospectiveResource])
def list_retrospectives(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    lifecycle_status: Annotated[str, Query(alias="lifecycleStatus")] = "active",
    job_target_id: Annotated[str | None, Query(alias="jobTargetId")] = None,
    application: AgentApplication = Depends(get_agent_application),
):
    service = _application(application, workspace_id)
    records = service.list_retrospectives(
        lifecycle_status=lifecycle_status,
        job_target_id=job_target_id,
    )
    return [_retrospective_resource(service, item) for item in records]


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
    service = _application(application, command.workspace_id)
    record = await service.create_retrospective(
        **values, idempotency_key=idempotency_key
    )
    return _retrospective_resource(service, record)


@router.get(
    "/api/interview-retrospectives/{retrospective_id}",
    response_model=RetrospectiveResource,
)
def get_retrospective(
    retrospective_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    service = _application(application, workspace_id)
    record = service.get_retrospective(retrospective_id)
    return _retrospective_resource(service, record)


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
    service = _application(application, command.workspace_id)
    record = service.update_retrospective(
        retrospective_id, **values, idempotency_key=idempotency_key
    )
    return _retrospective_resource(service, record)


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
    "/api/interview-retrospectives/{retrospective_id}/sources/{version_id}/clear",
    response_model=SourceVersionResource,
    response_model_exclude_none=True,
)
def clear_source(
    retrospective_id: str,
    version_id: str,
    command: VersionedRetrospectiveCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    record = _application(application, command.workspace_id).clear_source(
        retrospective_id,
        version_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    return source_version_resource(record, include_body=False)


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
        corrections=service.list_corrections(retrospective_id, cleanup_id),
        review_issues=service.list_transcript_review_issues(
            retrospective_id, cleanup_id
        ),
        work_items=service.list_cleanup_work_items(retrospective_id, cleanup_id),
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
        corrections=service.list_corrections(retrospective_id, cleanup.id),
        review_issues=service.list_transcript_review_issues(
            retrospective_id, cleanup.id
        ),
        work_items=service.list_cleanup_work_items(retrospective_id, cleanup.id),
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
        correction_decisions=tuple(
            item.model_dump() for item in command.correction_decisions
        ),
    )
    return _cleanup_resource(service, retrospective_id, cleanup_id)


@router.put(
    "/api/interview-retrospectives/{retrospective_id}/cleanup-runs/{cleanup_id}/document",
    response_model=CleanupVersionResource,
)
def update_clean_transcript_document(
    retrospective_id: str,
    cleanup_id: str,
    command: UpdateCleanTranscriptCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    del idempotency_key
    service = _application(application, command.workspace_id)
    service.update_clean_transcript_document(
        retrospective_id,
        cleanup_id,
        expected_version=command.expected_version,
        document_body=command.document_body,
        review_issue_decisions=tuple(
            item.model_dump() for item in command.review_issue_decisions
        ),
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
    return _retrospective_resource(service, record)


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/archive",
    response_model=RetrospectiveResource,
)
def archive_retrospective(
    retrospective_id: str,
    command: VersionedRetrospectiveCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    return _lifecycle(
        retrospective_id, command, idempotency_key, application, "archive"
    )


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/recycle",
    response_model=RetrospectiveResource,
)
def recycle_retrospective(
    retrospective_id: str,
    command: VersionedRetrospectiveCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    return _lifecycle(
        retrospective_id, command, idempotency_key, application, "recycle"
    )


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/restore",
    response_model=RetrospectiveResource,
)
def restore_retrospective(
    retrospective_id: str,
    command: VersionedRetrospectiveCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    return _lifecycle(
        retrospective_id, command, idempotency_key, application, "restore"
    )


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/deletion-impact",
    response_model=DeletionImpactResource,
)
def deletion_impact(
    retrospective_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    return _application(application, workspace_id).deletion_impact(retrospective_id)


@router.delete(
    "/api/interview-retrospectives/{retrospective_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_retrospective(
    retrospective_id: str,
    command: DeleteRetrospectiveCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    _application(application, command.workspace_id).delete_permanently(
        retrospective_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    return Response(status_code=204)


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/analysis-runs",
    response_model=AnalysisStartResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_analysis(
    retrospective_id: str,
    command: StartAnalysisCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    return await _application(application, command.workspace_id).start_analysis(
        retrospective_id,
        cleanup_version_id=command.cleanup_version_id,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/analysis-runs/{run_id}",
    response_model=AnalysisRunResource,
)
def get_analysis_run(
    retrospective_id: str,
    run_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    return analysis_run_resource(
        _application(application, workspace_id).get_analysis_run(
            retrospective_id, run_id
        )
    )


async def _analysis_control(
    retrospective_id, run_id, command, idempotency_key, application, action
):
    result = await getattr(_application(application, command.workspace_id), action)(
        retrospective_id,
        run_id,
        idempotency_key=idempotency_key,
    )
    if isinstance(result, dict):
        return result
    return analysis_run_resource(result)


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/analysis-runs/{run_id}/stop",
    response_model=AnalysisRunResource,
)
async def stop_analysis(
    retrospective_id: str,
    run_id: str,
    command: AnalysisControlCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    return await _analysis_control(
        retrospective_id, run_id, command, idempotency_key, application, "stop_analysis"
    )


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/analysis-runs/{run_id}/resume",
    response_model=AnalysisStartResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_analysis(
    retrospective_id: str,
    run_id: str,
    command: AnalysisControlCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    return await _analysis_control(
        retrospective_id,
        run_id,
        command,
        idempotency_key,
        application,
        "resume_analysis",
    )


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/analysis-runs/{run_id}/retry",
    response_model=AnalysisStartResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_analysis(
    retrospective_id: str,
    run_id: str,
    command: AnalysisControlCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    return await _analysis_control(
        retrospective_id,
        run_id,
        command,
        idempotency_key,
        application,
        "retry_analysis",
    )


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/questions",
    response_model=list[QuestionResource],
)
def list_questions(
    retrospective_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    return [
        question_resource(item)
        for item in _application(application, workspace_id).list_questions(
            retrospective_id
        )
    ]


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/questions/{question_id}/decision",
    response_model=QuestionResource,
)
async def decide_question(
    retrospective_id: str,
    question_id: str,
    command: QuestionDecisionCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    return question_resource(
        await _application(application, command.workspace_id).decide_question(
            retrospective_id,
            question_id,
            decision=command.decision,
            edited_text=command.edited_text,
            expected_version=command.expected_version,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/report",
    response_model=AnalysisReportResource | None,
)
def get_report(
    retrospective_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    result = _application(application, workspace_id).report(retrospective_id)
    if result is None:
        return None
    run, questions, analyses, gaps, items = result
    run_resource = analysis_run_resource(run)
    return {
        "analysisRun": run_resource,
        "questions": [question_resource(item) for item in questions],
        "analyses": [
            question_analysis_resource(
                item,
                tuple(gap for gap in gaps if gap.question_analysis_id == item.id),
            )
            for item in analyses
        ],
        "items": [analysis_work_item_resource(item) for item in items],
        "summary": run_resource["summary"] or {},
    }


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/candidates",
    response_model=list[AssetCandidateResource],
)
def list_candidates(
    retrospective_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    candidate_status: Annotated[str | None, Query(alias="status")] = None,
    application: AgentApplication = Depends(get_agent_application),
):
    return [
        asset_candidate_resource(item)
        for item in _application(application, workspace_id).list_candidates(
            retrospective_id, status=candidate_status
        )
    ]


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/candidates/{candidate_id}/decision",
    response_model=AssetCandidateResource,
)
async def decide_candidate(
    retrospective_id: str,
    candidate_id: str,
    command: CandidateDecisionCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    record = await _application(application, command.workspace_id).decide_candidate(
        retrospective_id,
        candidate_id,
        action=command.action,
        target_resource_id=command.target_resource_id,
        action_payload=command.action_payload,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    return asset_candidate_resource(record)


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/candidates/{candidate_id}/practice-link",
    response_model=ImmediatePracticeResource,
)
def candidate_practice_link(
    retrospective_id: str,
    candidate_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    service = _application(application, workspace_id)
    candidate = service.repository.get_asset_candidate(candidate_id)
    if (
        candidate.retrospective_id != retrospective_id
        or candidate.status != "confirmed"
        or candidate.target_resource_type != "review_question"
        or candidate.target_resource_id is None
    ):
        raise ValueError("只有已关联的正式题库题目可以立即练习")
    return {
        "questionId": candidate.target_resource_id,
        "href": service.immediate_practice_link(
            retrospective_id, candidate.target_resource_id
        ),
    }


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/candidates/batch-decision",
    response_model=list[BatchCandidateDecisionResult],
)
async def batch_decide_candidates(
    retrospective_id: str,
    command: BatchCandidateDecisionCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    service = _application(application, command.workspace_id)
    results: list[dict[str, object]] = []
    for item in command.decisions:
        try:
            record = await service.decide_candidate(
                retrospective_id,
                item.candidate_id,
                action=item.action,
                target_resource_id=item.target_resource_id,
                action_payload=item.action_payload,
                expected_version=item.expected_version,
                idempotency_key=item.idempotency_key,
            )
            results.append(
                {
                    "candidateId": item.candidate_id,
                    "status": "completed",
                    "candidate": asset_candidate_resource(record),
                    "errorCode": None,
                }
            )
        except Exception as error:
            results.append(
                {
                    "candidateId": item.candidate_id,
                    "status": "failed",
                    "candidate": None,
                    "errorCode": str(getattr(error, "code", type(error).__name__)),
                }
            )
    return results


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/actions",
    response_model=list[ActionItemResource],
)
def list_actions(
    retrospective_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    return [
        action_item_resource(item)
        for item in _application(application, workspace_id).list_actions(
            retrospective_id
        )
    ]


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/actions/{action_id}/decision",
    response_model=ActionItemResource,
)
def decide_action(
    retrospective_id: str,
    action_id: str,
    command: ActionDecisionCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    record = _application(application, command.workspace_id).decide_action(
        retrospective_id,
        action_id,
        decision=command.decision,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    return action_item_resource(record)


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/publication-drafts",
    response_model=PublicationDraftResource,
    status_code=status.HTTP_201_CREATED,
)
async def create_publication_draft(
    retrospective_id: str,
    command: PublicationDraftCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    draft = await _application(
        application, command.workspace_id
    ).create_publication_draft(
        retrospective_id,
        selected_sections=tuple(command.selected_sections),
        idempotency_key=idempotency_key,
    )
    return {
        "id": draft.id,
        "documentType": draft.document_type,
        "title": draft.title,
        "markdown": draft.markdown,
        "status": draft.status,
        "version": draft.version,
    }


def _correction_resource(item):
    return {
        "id": item.id,
        "retrospectiveId": item.retrospective_id,
        "chatMessageId": item.chat_message_id,
        "proposalType": item.proposal_type,
        "targetQuestionId": item.target_question_id,
        "sourceCleanupVersionId": item.source_cleanup_version_id,
        "sourceAnalysisRunId": item.source_analysis_run_id,
        "before": item.before,
        "after": item.after,
        "rationale": item.rationale,
        "expectedVersion": item.expected_version,
        "status": item.status,
        "resultingCleanupVersionId": item.resulting_cleanup_version_id,
        "resultingAnalysisRunId": item.resulting_analysis_run_id,
        "version": item.version,
        "createdAt": item.created_at,
        "updatedAt": item.updated_at,
    }


@router.get(
    "/api/interview-retrospectives/{retrospective_id}/conversation",
    response_model=RetrospectiveConversationResource,
)
def get_conversation(
    retrospective_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    result = _application(application, workspace_id).conversation(retrospective_id)
    latest = result["latestExecution"]
    return {
        "sessionId": result["sessionId"],
        "messages": [
            {
                "id": item.id,
                "executionId": item.execution_id,
                "role": item.role,
                "content": item.content,
                "messageKind": item.message_kind,
                "payload": item.payload,
                "createdAt": item.created_at,
            }
            for item in result["messages"]
        ],
        "proposals": [_correction_resource(item) for item in result["proposals"]],
        "latestExecution": None
        if latest is None
        else {
            "id": latest.id,
            "status": latest.status,
            "errorCode": latest.error_code,
            "createdAt": latest.created_at,
            "finishedAt": latest.finished_at,
        },
    }


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/conversation/messages",
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_conversation_message(
    retrospective_id: str,
    command: RetrospectiveChatCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    execution = await _application(application, command.workspace_id).send_chat_message(
        retrospective_id,
        message=command.message,
        selected_question_id=command.selected_question_id,
    )
    return {"executionId": execution.id, "status": execution.status}


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/conversation/executions/{execution_id}/stop"
)
async def stop_conversation(
    retrospective_id: str,
    execution_id: str,
    command: RetrospectiveChatControlCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    execution = await _application(application, command.workspace_id).stop_chat(
        retrospective_id, execution_id
    )
    return {"executionId": execution.id, "status": execution.status}


@router.post(
    "/api/interview-retrospectives/{retrospective_id}/corrections/{proposal_id}/decision",
    response_model=CorrectionProposalResource,
)
async def decide_correction(
    retrospective_id: str,
    proposal_id: str,
    command: CorrectionDecisionCommand,
    idempotency_key: IdempotencyKey,
    application: AgentApplication = Depends(get_agent_application),
):
    del idempotency_key
    proposal = await _application(application, command.workspace_id).decide_correction(
        retrospective_id, proposal_id, decision=command.decision
    )
    return _correction_resource(proposal)
