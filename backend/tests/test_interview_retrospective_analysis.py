from __future__ import annotations

import pytest

from app.application.session_service import ProductRepository
from app.graphs.interview_retrospective_analysis import finalize_report
from app.infrastructure.runtime_database import connect_runtime_database
from app.interview_retrospectives.errors import RetrospectiveCleanupNotConfirmed
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository
from app.interview_retrospectives.service import InterviewRetrospectiveService
from app.job_targets.repository import JobTargetRepository


def _analysis_fixture(tmp_path):
    connection = connect_runtime_database(tmp_path)
    products = ProductRepository(connection)
    targets = JobTargetRepository(connection)
    repository = InterviewRetrospectiveRepository(connection)
    service = InterviewRetrospectiveService(
        workspace_id="w1", repository=repository, job_targets=targets
    )
    target = targets.create_target(
        workspace_id="w1",
        role_name="后端工程师",
        seniority="3-5 年",
        company_name="示例公司",
        source_url=None,
    )
    analysis = products.create_session(
        workspace_id="w1",
        kind="interview.retrospective.analysis",
        title="复盘分析",
        visibility="system",
    )
    chat = products.create_session(
        workspace_id="w1", kind="interview.retrospective.chat", title="复盘讨论"
    )
    retrospective = service.create(
        job_target_id=target.id,
        title="示例公司一面",
        round_label="一面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        analysis_session_id=analysis.id,
        chat_session_id=chat.id,
        idempotency_key="create-analysis-fixture",
    )
    source = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="面试官：介绍缓存治理\n候选人：我负责双写一致性。",
        file_name=None,
        idempotency_key="source-analysis-fixture",
    )
    cleanup = service.create_cleanup_version(
        retrospective.id,
        source_version_id=source.id,
        input_digest="a" * 64,
        idempotency_key="cleanup-analysis-fixture",
    )
    cleanup = service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(
            {
                "speaker_role": "interviewer",
                "raw_speaker_label": "面试官",
                "display_name": "面试官",
                "body": "介绍缓存治理",
                "source_start": 0,
                "source_end": 10,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
            {
                "speaker_role": "candidate",
                "raw_speaker_label": "候选人",
                "display_name": "候选人",
                "body": "我负责双写一致性",
                "source_start": 11,
                "source_end": 22,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
        ),
    )
    return connection, service, repository, retrospective, cleanup


def test_analysis_requires_confirmed_cleanup(tmp_path) -> None:
    connection, service, _repository, retrospective, cleanup = _analysis_fixture(
        tmp_path
    )

    with pytest.raises(RetrospectiveCleanupNotConfirmed):
        service.create_analysis_run(
            retrospective.id,
            cleanup.id,
            input_digest="b" * 64,
            context_snapshot={"targetId": retrospective.job_target_id},
            idempotency_key="analysis-unconfirmed",
        )
    connection.close()


def test_analysis_run_is_idempotent_and_starts_with_extraction_work(tmp_path) -> None:
    connection, service, repository, retrospective, cleanup = _analysis_fixture(
        tmp_path
    )
    cleanup = service.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="confirm-analysis-fixture",
    )

    first = service.create_analysis_run(
        retrospective.id,
        cleanup.id,
        input_digest="c" * 64,
        context_snapshot={"targetId": retrospective.job_target_id},
        idempotency_key="analysis-start",
    )
    replay = service.create_analysis_run(
        retrospective.id,
        cleanup.id,
        input_digest="c" * 64,
        context_snapshot={"targetId": retrospective.job_target_id},
        idempotency_key="analysis-start",
    )
    same_digest = service.create_analysis_run(
        retrospective.id,
        cleanup.id,
        input_digest="c" * 64,
        context_snapshot={"targetId": retrospective.job_target_id},
        idempotency_key="analysis-start-same-digest",
    )

    assert replay.id == first.id
    assert same_digest.id == first.id
    assert first.stage == "question_extraction"
    assert first.total_items == 1
    assert [
        item.work_key for item in repository.list_analysis_work_items(first.id)
    ] == ["question_extraction"]
    connection.close()


def test_questions_persist_with_original_and_inferred_decision_defaults(
    tmp_path,
) -> None:
    connection, service, repository, retrospective, cleanup = _analysis_fixture(
        tmp_path
    )
    cleanup = service.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="confirm-question-fixture",
    )
    run = service.create_analysis_run(
        retrospective.id,
        cleanup.id,
        input_digest="d" * 64,
        context_snapshot={"targetId": retrospective.job_target_id},
        idempotency_key="analysis-questions",
    )
    segments = repository.list_segments(cleanup.id)

    questions = repository.replace_question_units(
        run.id,
        questions=(
            {
                "ordinal": 1,
                "question_kind": "project_experience",
                "origin": "original",
                "question_text": "介绍缓存治理",
                "question_segment_ids": (segments[0].id,),
                "answer_segment_ids": (segments[1].id,),
                "inference_basis": "",
                "confidence": 0.99,
            },
            {
                "ordinal": 2,
                "question_kind": "technical_knowledge",
                "origin": "inferred",
                "question_text": "双写失败如何恢复？",
                "question_segment_ids": (),
                "answer_segment_ids": (segments[1].id,),
                "inference_basis": "回答提到了双写一致性",
                "confidence": 0.7,
            },
        ),
    )

    assert [item.origin for item in questions] == ["original", "inferred"]
    assert [item.decision_status for item in questions] == ["confirmed", "pending"]
    assert questions[0].question_segment_ids == (segments[0].id,)
    assert questions[1].inference_basis == "回答提到了双写一致性"
    connection.close()


def test_final_report_excludes_pending_inferred_questions_and_has_no_score() -> None:
    report = finalize_report(
        questions=(
            {
                "id": "q1",
                "ordinal": 1,
                "origin": "original",
                "decisionStatus": "confirmed",
            },
            {
                "id": "q2",
                "ordinal": 2,
                "origin": "inferred",
                "decisionStatus": "pending",
            },
        ),
        analyses=(
            {"questionUnitId": "q1", "verdict": "strong"},
            {"questionUnitId": "q2", "verdict": "high_risk"},
        ),
    )

    assert report == {
        "includedQuestionIds": ["q1"],
        "questionCount": 1,
        "verdictCounts": {"strong": 1},
    }
    assert "overallScore" not in report


def test_retry_reuses_question_identity_and_preserves_previous_run_analysis(
    tmp_path,
) -> None:
    connection, service, repository, retrospective, cleanup = _analysis_fixture(
        tmp_path
    )
    cleanup = service.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="confirm-retry-history",
    )
    first_run = service.create_analysis_run(
        retrospective.id,
        cleanup.id,
        input_digest="2" * 64,
        context_snapshot={"targetId": retrospective.job_target_id},
        idempotency_key="analysis-history-first",
    )
    segments = repository.list_segments(cleanup.id)
    payload = (
        {
            "ordinal": 1,
            "question_kind": "project_experience",
            "origin": "original",
            "question_text": "介绍缓存治理",
            "question_segment_ids": (segments[0].id,),
            "answer_segment_ids": (segments[1].id,),
            "inference_basis": "",
            "confidence": 0.99,
        },
    )
    original_question = repository.replace_question_units(
        first_run.id, questions=payload
    )[0]
    repository.save_question_analysis(
        first_run.id,
        original_question.id,
        output={
            "verdict": "strong",
            "strengths": [],
            "improvements": [],
            "omissions": [],
            "gaps": [],
            "evidenceLevel": "internal_evidence",
            "confidence": 0.9,
            "improvementOutline": [],
            "suggestedAnswer": "",
        },
        source_excerpt="我负责双写一致性",
    )
    repository.mark_analysis_completed(first_run.id, summary={})
    retry_run = service.create_analysis_run(
        retrospective.id,
        cleanup.id,
        input_digest="2" * 64,
        context_snapshot={"targetId": retrospective.job_target_id},
        retry_of_analysis_run_id=first_run.id,
        idempotency_key="analysis-history-retry",
    )

    retried_question = repository.replace_question_units(
        retry_run.id, questions=payload
    )[0]

    assert retried_question.id == original_question.id
    assert repository.list_question_analyses(first_run.id)[0].verdict == "strong"
    connection.close()
