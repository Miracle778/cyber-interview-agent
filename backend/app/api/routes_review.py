from __future__ import annotations

from secrets import randbits
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.review.models import ReviewRoundSettings
from app.schemas.review import (
    ActiveQuestionResource,
    CreateCurationSessionCommand,
    CreateQuestionBatchCommand,
    CreateReviewDiscussionCommand,
    CreateReviewRoundCommand,
    CurationSessionResource,
    CurationCommandReceiptResource,
    DiscussionSessionResource,
    QuestionBatchResource,
    QuestionCandidateResource,
    ReviewRoundResource,
    ReviewAnswerReceiptResource,
    RewriteQuestionCandidateCommand,
    SkipReviewInputCommand,
    SubmitReviewInputCommand,
    RetryReviewEvaluationCommand,
    SubmitCurationCommand,
    UpdateQuestionCandidateCommand,
)


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
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.review(workspace_id).list_curation_resources()


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
    "/curation-sessions/{session_id}/commands",
    response_model=CurationCommandReceiptResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_curation_command(
    session_id: str,
    command: SubmitCurationCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_session(session_id)
    return await review.execute_curation_command(
        session_id,
        text=command.text,
        summary_version=command.summary_version,
        idempotency_key=command.idempotency_key,
    )


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
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.review(workspace_id).list_candidate_resources(
        query=query,
        topic=topic,
        difficulty=difficulty,
        source_id=source_id,
        status=candidate_status,
        limit=50,
        offset=(page - 1) * 50,
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
    response_model=QuestionBatchResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rewrite_question_candidate(
    candidate_id: str,
    command: RewriteQuestionCandidateCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    review = application.locate_review_candidate(candidate_id)
    candidate = review.repository.get_candidate(candidate_id)
    batch = await review.create_question_batch(
        source_refs=candidate.source_refs,
        rewrite_feedback=command.feedback,
        rewrite_of_batch_id=candidate.batch_id,
    )
    return await review.batch_resource(batch.id)


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
    )
    return review.answer_receipt_resource(receipt)


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
        round_id, ordinal=command.ordinal, message=command.message
    )
