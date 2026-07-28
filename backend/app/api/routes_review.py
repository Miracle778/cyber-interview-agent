from __future__ import annotations

from secrets import randbits
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.review.models import ReviewRoundSettings
from app.schemas.review import (
    ActiveQuestionResource,
    ControlCurationSessionCommand,
    CreateCurationSessionCommand,
    CreateQuestionBatchCommand,
    CreateReviewDiscussionCommand,
    CreateReviewRoundCommand,
    CurationSessionResource,
    CurationCommandReceiptResource,
    AcceptedCurationCommandResource,
    AcceptedCurationSeedRetryResource,
    AcceptedBulkPublicationResource,
    BulkPublicationPreflightResource,
    BulkPublicationResource,
    CandidateOriginSessionResource,
    DiscussionSessionResource,
    QuestionBatchResource,
    QuestionCandidateResource,
    ReviewRoundResource,
    ReviewTurnReceiptResource,
    ReviewAnswerReceiptResource,
    RewriteQuestionCandidateCommand,
    SkipReviewInputCommand,
    SubmitReviewInputCommand,
    RetryReviewEvaluationCommand,
    RetryCurationSeedTaskCommand,
    SubmitCurationCommand,
    StartBulkPublicationCommand,
    RetryBulkPublicationCommand,
    UpdateQuestionCandidateCommand,
    UpdateQuestionCandidateNoteCommand,
    PublishQuestionCandidateCommand,
    UpdateActiveQuestionVersionCommand,
    DeleteQuestionCandidateCommand,
    BulkDeleteQuestionCandidatesCommand,
    BulkConfirmQuestionCandidatesCommand,
    QuestionDeletionResultResource,
    QuestionConfirmationResultResource,
)
from app.schemas.agent import ExecutionResource


router = APIRouter(prefix="/api/review", tags=["review"])


@router.post(
    "/curation-sessions",
    response_model=CurationSessionResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_curation_session(
    command: CreateCurationSessionCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.review(command.workspace_id).create_curation_session(
        source_refs=tuple(command.source_refs)
    )


@router.get(
    "/curation-sessions", response_model=list[CurationSessionResource]
)
async def list_curation_sessions(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    deleted_only: Annotated[bool, Query(alias="deletedOnly")] = False,
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.review(workspace_id).list_curation_resources(
        deleted_only=deleted_only
    )


@router.get(
    "/curation-sessions/{session_id}",
    response_model=CurationSessionResource,
)
async def get_curation_session(
    session_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_session(session_id)
    return await review.curation_resource(session_id)


@router.post(
    "/curation-sessions/{session_id}/pause",
    response_model=CurationSessionResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def pause_curation_session(
    session_id: str,
    command: ControlCurationSessionCommand,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=200),
    ],
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_session(session_id)
    return await review.pause_curation_session(
        session_id,
        expected_batch_version=command.expected_batch_version,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/curation-sessions/{session_id}/resume",
    response_model=CurationSessionResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_curation_session(
    session_id: str,
    command: ControlCurationSessionCommand,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=200),
    ],
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_session(session_id)
    return await review.resume_curation_session(
        session_id,
        expected_batch_version=command.expected_batch_version,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/curation-sessions/{session_id}/terminate",
    response_model=CurationSessionResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def terminate_curation_session(
    session_id: str,
    command: ControlCurationSessionCommand,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=200),
    ],
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_session(session_id)
    return await review.terminate_curation_session(
        session_id,
        expected_batch_version=command.expected_batch_version,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/curation-sessions/{session_id}/seed-tasks/{seed_task_id}/retry",
    response_model=AcceptedCurationSeedRetryResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_curation_seed_task(
    session_id: str,
    seed_task_id: str,
    command: RetryCurationSeedTaskCommand,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=200),
    ],
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_session(session_id)
    return await review.retry_curation_seed_task(
        session_id,
        seed_task_id=seed_task_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/curation-sessions/{session_id}/retry",
    response_model=CurationSessionResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_curation_session(
    session_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_session(session_id)
    return await review.retry_curation_session(session_id)


@router.post(
    "/curation-sessions/{session_id}/commands",
    response_model=AcceptedCurationCommandResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_curation_command(
    session_id: str,
    command: SubmitCurationCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_session(session_id)
    return await review.submit_curation_command(
        session_id,
        text=command.text,
        summary_version=command.summary_version,
        idempotency_key=command.idempotency_key,
        provider_model_id=command.provider_model_id,
        reasoning_effort=command.reasoning_effort,
    )


@router.post(
    "/curation-commands/{command_id}/retry",
    response_model=AcceptedCurationCommandResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_curation_command(
    command_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_curation_command(command_id)
    return await review.retry_curation_command(command_id)


@router.post(
    "/curation-commands/{command_id}/abandon",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def abandon_curation_command(
    command_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_curation_command(command_id)
    await review.abandon_curation_command(command_id)


@router.get(
    "/curation-sessions/{session_id}/bulk-publication/preflight",
    response_model=BulkPublicationPreflightResource,
)
async def preflight_bulk_publication(
    session_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_session(session_id)
    return review.preflight_bulk_publication(session_id)


@router.post(
    "/curation-sessions/{session_id}/bulk-publications",
    response_model=AcceptedBulkPublicationResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_bulk_publication(
    session_id: str,
    command: StartBulkPublicationCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_session(session_id)
    return await review.start_bulk_publication(
        session_id,
        summary_version=command.summary_version,
        idempotency_key=command.idempotency_key,
        candidate_ids=tuple(command.candidate_ids),
        confirmed_ai_candidate_ids=tuple(command.confirmed_ai_candidate_ids),
    )


@router.post(
    "/bulk-publications/{operation_id}/retry",
    response_model=AcceptedBulkPublicationResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_bulk_publication(
    operation_id: str,
    command: RetryBulkPublicationCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_bulk_publication(operation_id)
    return await review.retry_bulk_publication(
        operation_id, idempotency_key=command.idempotency_key
    )


@router.get(
    "/bulk-publications/latest",
    response_model=BulkPublicationResource | None,
)
async def get_latest_bulk_publication(
    session_id: Annotated[str, Query(alias="sessionId")],
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_session(session_id)
    return review.latest_bulk_publication_resource(session_id)


@router.get(
    "/bulk-publications/{operation_id}",
    response_model=BulkPublicationResource,
)
async def get_bulk_publication(
    operation_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_bulk_publication(operation_id)
    return review.bulk_publication_resource(operation_id)


@router.post(
    "/question-batches",
    response_model=QuestionBatchResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_question_batch(
    command: CreateQuestionBatchCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.review(command.workspace_id)
    batch = await review.create_question_batch(
        source_refs=tuple(command.source_refs),
        rewrite_feedback=command.rewrite_feedback,
        rewrite_of_batch_id=command.rewrite_of_batch_id,
    )
    return await review.batch_resource(batch.id)


@router.get("/question-batches", response_model=list[QuestionBatchResource])
async def list_question_batches(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    batch_status: Annotated[str | None, Query(alias="status")] = None,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.review(workspace_id)
    return [
        await review.batch_resource(item.id)
        for item in review.list_batches(status=batch_status)
    ]


@router.get(
    "/question-batches/{batch_id}", response_model=QuestionBatchResource
)
async def get_question_batch(
    batch_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_batch(batch_id)
    return await review.batch_resource(batch_id)


@router.get(
    "/question-candidates", response_model=list[QuestionCandidateResource]
)
async def list_question_candidates(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    query: str | None = None,
    topic: str | None = None,
    difficulty: str | None = None,
    source_id: Annotated[str | None, Query(alias="sourceId")] = None,
    candidate_status: Annotated[str | None, Query(alias="status")] = None,
    page: int = Query(default=1, ge=1),
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=500)] = 50,
    deleted_only: Annotated[bool, Query(alias="deletedOnly")] = False,
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.review(workspace_id).list_candidate_resources(
        query=query,
        topic=topic,
        difficulty=difficulty,
        source_id=source_id,
        status=candidate_status,
        deleted_only=deleted_only,
        limit=page_size,
        offset=(page - 1) * page_size,
    )


@router.get(
    "/question-candidates/{candidate_id}",
    response_model=QuestionCandidateResource,
)
async def get_question_candidate(
    candidate_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_candidate(candidate_id)
    return await review.candidate_resource(candidate_id)


@router.get(
    "/question-candidates/{candidate_id}/origin-session",
    response_model=CandidateOriginSessionResource,
)
async def get_question_candidate_origin_session(
    candidate_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_candidate(candidate_id)
    return await review.candidate_origin_session_resource(candidate_id)


@router.post(
    "/question-candidates/{candidate_id}/delete",
    response_model=QuestionDeletionResultResource,
)
async def delete_question_candidate(
    candidate_id: str,
    command: DeleteQuestionCandidateCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_candidate(candidate_id)
    return review.delete_candidates(
        ((candidate_id, command.expected_version),),
        idempotency_key=command.idempotency_key,
        reason=command.reason,
    )


@router.post(
    "/question-candidates/bulk-delete",
    response_model=QuestionDeletionResultResource,
)
async def bulk_delete_question_candidates(
    command: BulkDeleteQuestionCandidatesCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    return application.review(command.workspace_id).delete_candidates(
        tuple((item.candidate_id, item.expected_version) for item in command.items),
        idempotency_key=command.idempotency_key,
        reason=command.reason,
    )


@router.post(
    "/question-candidates/bulk-confirm",
    response_model=QuestionConfirmationResultResource,
)
async def bulk_confirm_question_candidates(
    command: BulkConfirmQuestionCandidatesCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    return application.review(command.workspace_id).confirm_candidates(
        tuple(command.candidate_ids),
        idempotency_key=command.idempotency_key,
    )


@router.post(
    "/question-candidates/{candidate_id}/restore",
    response_model=QuestionCandidateResource,
)
async def restore_question_candidate(
    candidate_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_candidate(candidate_id)
    return await review.restore_candidate(candidate_id)


@router.patch(
    "/question-candidates/{candidate_id}",
    response_model=QuestionCandidateResource,
)
async def update_question_candidate(
    candidate_id: str,
    command: UpdateQuestionCandidateCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    values = command.model_dump(exclude={"version"}, exclude_none=True)
    review = application.locate_review_candidate(candidate_id)
    return await review.update_candidate(
        candidate_id, expected_version=command.version, values=values
    )


@router.post(
    "/question-candidates/{candidate_id}/rewrite",
    response_model=CurationSessionResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rewrite_question_candidate(
    candidate_id: str,
    command: RewriteQuestionCandidateCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_candidate(candidate_id)
    return await review.rewrite_candidate_in_context(
        candidate_id, feedback=command.feedback
    )


@router.put(
    "/question-candidates/{candidate_id}/note",
    response_model=QuestionCandidateResource,
)
async def update_question_candidate_note(
    candidate_id: str,
    command: UpdateQuestionCandidateNoteCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_candidate(candidate_id)
    return await review.update_candidate_review_note(
        candidate_id, note=command.note
    )


@router.post(
    "/question-candidates/{candidate_id}/publish",
    response_model=QuestionCandidateResource,
)
async def publish_question_candidate(
    candidate_id: str,
    command: PublishQuestionCandidateCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_candidate(candidate_id)
    return await review.publish_candidate(
        candidate_id,
        idempotency_key=command.idempotency_key,
        confirm_ai_supplement=command.confirm_ai_supplement,
    )


@router.post(
    "/question-candidates/{candidate_id}/update-active-version",
    response_model=QuestionCandidateResource,
)
async def update_active_question_version(
    candidate_id: str,
    command: UpdateActiveQuestionVersionCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_candidate(candidate_id)
    return await review.update_active_question_version(
        candidate_id,
        target_question_id=command.target_question_id,
        expected_active_hash=command.expected_active_hash,
        idempotency_key=command.idempotency_key,
        confirm_ai_supplement=command.confirm_ai_supplement,
    )


@router.get("/questions", response_model=list[ActiveQuestionResource])
async def list_active_questions(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    topic: str | None = None,
    difficulty: str | None = None,
    application: AgentApplication = Depends(get_agent_application),
):
    records = application.review(workspace_id).list_questions(
        topic=topic, difficulty=difficulty
    )
    return [
        {
            "id": item.snapshot.question_id,
            "title": item.snapshot.title,
            "question_text": item.snapshot.question_text,
            "reference_answer": item.snapshot.reference_answer,
            "topics": item.snapshot.topics,
            "difficulty": item.snapshot.difficulty,
            "key_points": item.snapshot.key_points,
            "follow_ups": item.snapshot.follow_ups,
            "draft_id": item.draft_id,
            "publication_id": item.publication_id,
            "published_at": item.published_at,
            "question_type": item.question_type,
            "project_claim_id": item.project_claim_id,
            "project_dimension": item.project_dimension,
            "source_job_target_id": item.source_job_target_id,
            "source_ids": item.source_ids,
        }
        for item in records
    ]


@router.post(
    "/rounds",
    response_model=ReviewRoundResource,
    status_code=status.HTTP_201_CREATED,
)
async def create_review_round(
    command: CreateReviewRoundCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.review(command.workspace_id)
    round_record = await review.create_round(
        ReviewRoundSettings(
            topics=tuple(command.selected_topics),
            difficulties=tuple(command.difficulties),
            mode=command.mode,
            question_count=command.question_count,
            allow_follow_up=command.allow_follow_up,
            seed=command.seed if command.seed is not None else randbits(63),
            answer_model_id=command.answer_model_id,
            reasoning_effort=command.reasoning_effort,
            source_id=command.source_id,
        )
    )
    return await review.round_resource(round_record.id)


@router.get("/rounds", response_model=list[ReviewRoundResource])
async def list_review_rounds(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.review(workspace_id).list_round_resources()


@router.get("/rounds/{round_id}", response_model=ReviewRoundResource)
async def get_review_round(
    round_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_round(round_id)
    return await review.round_resource(round_id)


@router.post(
    "/rounds/{round_id}/answers",
    response_model=ReviewAnswerReceiptResource,
    status_code=202,
)
async def submit_review_answer(
    round_id: str,
    command: SubmitReviewInputCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_round(round_id)
    receipt = await review.submit_answer(
        round_id,
        request_id=command.input_request_id,
        version=command.version,
        idempotency_key=command.idempotency_key,
        value=command.value,
        provider_model_id=command.provider_model_id,
        reasoning_effort=command.reasoning_effort,
    )
    return review.answer_receipt_resource(receipt)


@router.post(
    "/rounds/{round_id}/turns",
    response_model=ReviewTurnReceiptResource,
    status_code=202,
)
async def submit_review_turn(
    round_id: str,
    command: SubmitReviewInputCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_round(round_id)
    return await review.submit_turn(
        round_id,
        request_id=command.input_request_id,
        version=command.version,
        idempotency_key=command.idempotency_key,
        value=command.value,
        provider_model_id=command.provider_model_id,
        reasoning_effort=command.reasoning_effort,
    )


@router.post(
    "/rounds/{round_id}/retry-evaluation",
    response_model=ReviewAnswerReceiptResource,
    status_code=202,
)
async def retry_review_evaluation(
    round_id: str,
    command: RetryReviewEvaluationCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_round(round_id)
    receipt = await review.retry_evaluation(
        round_id, idempotency_key=command.idempotency_key
    )
    return review.answer_receipt_resource(receipt)


@router.post(
    "/rounds/{round_id}/retry",
    response_model=ReviewRoundResource,
    status_code=202,
)
async def retry_review_round(
    round_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_round(round_id)
    await review.retry_round(round_id)
    return await review.round_resource(round_id)


@router.post("/rounds/{round_id}/skip", response_model=ReviewRoundResource)
async def skip_review_question(
    round_id: str,
    command: SkipReviewInputCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_round(round_id)
    await review.skip(
        round_id,
        request_id=command.input_request_id,
        version=command.version,
        idempotency_key=command.idempotency_key,
    )
    return await review.round_resource(round_id)


@router.post(
    "/rounds/{round_id}/interrupt-evaluation",
    response_model=ReviewRoundResource,
)
async def interrupt_review_evaluation(
    round_id: str,
    command: RetryReviewEvaluationCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_round(round_id)
    await review.interrupt_evaluation(
        round_id, idempotency_key=command.idempotency_key
    )
    return await review.round_resource(round_id)


@router.post("/rounds/{round_id}/cancel", response_model=ReviewRoundResource)
async def cancel_review_round(
    round_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_round(round_id)
    await review.cancel(round_id)
    return await review.round_resource(round_id)


@router.post(
    "/rounds/{round_id}/discussions",
    response_model=DiscussionSessionResource,
    status_code=status.HTTP_201_CREATED,
)
async def create_review_discussion(
    round_id: str,
    command: CreateReviewDiscussionCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_round(round_id)
    return await review.create_discussion(
        round_id, ordinal=command.ordinal
    )


@router.post(
    "/rounds/{round_id}/discussions/{session_id}/retry",
    response_model=ExecutionResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_review_discussion(
    round_id: str,
    session_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_round(round_id)
    return await review.retry_discussion(round_id, session_id=session_id)
