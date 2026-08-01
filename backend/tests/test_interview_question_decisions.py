from __future__ import annotations

import pytest

from app.interview_retrospectives.errors import (
    RetrospectiveIdempotencyConflict,
    RetrospectiveVersionConflict,
)
from tests.test_interview_retrospective_analysis import _analysis_fixture


def test_confirming_inferred_question_schedules_only_local_recompute(tmp_path) -> None:
    connection, service, repository, retrospective, cleanup = _analysis_fixture(
        tmp_path
    )
    cleanup = service.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="confirm-decision-fixture",
    )
    run = service.create_analysis_run(
        retrospective.id,
        cleanup.id,
        input_digest="e" * 64,
        context_snapshot={"targetId": retrospective.job_target_id},
        idempotency_key="analysis-decision",
    )
    segment = repository.list_segments(cleanup.id)[1]
    question = repository.replace_question_units(
        run.id,
        questions=(
            {
                "ordinal": 1,
                "question_kind": "technical_knowledge",
                "origin": "inferred",
                "question_text": "双写失败如何恢复？",
                "question_segment_ids": (),
                "answer_segment_ids": (segment.id,),
                "inference_basis": "回答提到了双写",
                "confidence": 0.72,
            },
        ),
    )[0]

    decided = service.decide_question(
        retrospective.id,
        question.id,
        decision="confirmed",
        edited_text="双写失败时如何恢复一致性？",
        expected_version=question.version,
        idempotency_key="question-confirm",
    )
    replay = service.decide_question(
        retrospective.id,
        question.id,
        decision="confirmed",
        edited_text="双写失败时如何恢复一致性？",
        expected_version=question.version,
        idempotency_key="question-confirm",
    )
    work_keys = [item.work_key for item in repository.list_analysis_work_items(run.id)]

    assert decided.decision_status == "confirmed"
    assert replay.id == decided.id
    assert replay.version == decided.version
    assert decided.question_text == "双写失败时如何恢复一致性？"
    assert work_keys == [
        "question_extraction",
        f"question_analysis:{question.id}",
        "gap_verification",
        "candidate_generation",
        "final_projection",
    ]
    connection.close()


def test_question_decision_rejects_conflicting_idempotency_replay(tmp_path) -> None:
    connection, service, repository, retrospective, cleanup = _analysis_fixture(
        tmp_path
    )
    cleanup = service.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="confirm-conflict-fixture",
    )
    run = service.create_analysis_run(
        retrospective.id,
        cleanup.id,
        input_digest="1" * 64,
        context_snapshot={"targetId": retrospective.job_target_id},
        idempotency_key="analysis-conflict",
    )
    segment = repository.list_segments(cleanup.id)[1]
    question = repository.replace_question_units(
        run.id,
        questions=(
            {
                "ordinal": 1,
                "question_kind": "unknown",
                "origin": "inferred",
                "question_text": "推断问题",
                "question_segment_ids": (),
                "answer_segment_ids": (segment.id,),
                "inference_basis": "回答内容",
                "confidence": 0.5,
            },
        ),
    )[0]
    service.decide_question(
        retrospective.id,
        question.id,
        decision="confirmed",
        edited_text=None,
        expected_version=question.version,
        idempotency_key="question-conflict",
    )

    with pytest.raises(RetrospectiveIdempotencyConflict):
        service.decide_question(
            retrospective.id,
            question.id,
            decision="rejected",
            edited_text=None,
            expected_version=question.version,
            idempotency_key="question-conflict",
        )
    connection.close()


def test_question_decision_enforces_expected_version(tmp_path) -> None:
    connection, service, repository, retrospective, cleanup = _analysis_fixture(
        tmp_path
    )
    cleanup = service.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="confirm-version-fixture",
    )
    run = service.create_analysis_run(
        retrospective.id,
        cleanup.id,
        input_digest="f" * 64,
        context_snapshot={"targetId": retrospective.job_target_id},
        idempotency_key="analysis-version",
    )
    segment = repository.list_segments(cleanup.id)[1]
    question = repository.replace_question_units(
        run.id,
        questions=(
            {
                "ordinal": 1,
                "question_kind": "unknown",
                "origin": "inferred",
                "question_text": "推断问题",
                "question_segment_ids": (),
                "answer_segment_ids": (segment.id,),
                "inference_basis": "回答内容",
                "confidence": 0.5,
            },
        ),
    )[0]

    with pytest.raises(RetrospectiveVersionConflict):
        service.decide_question(
            retrospective.id,
            question.id,
            decision="rejected",
            edited_text=None,
            expected_version=question.version + 1,
            idempotency_key="question-stale",
        )
    connection.close()
