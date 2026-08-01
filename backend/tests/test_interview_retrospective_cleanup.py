from __future__ import annotations

import pytest

from app.application.session_service import ProductRepository
from app.graphs.interview_retrospective_cleanup import (
    create_source_windows,
    reduce_cleanup_segments,
)
from app.infrastructure.runtime_database import connect_runtime_database
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository
from app.interview_retrospectives.service import InterviewRetrospectiveService
from app.job_targets.repository import JobTargetRepository


def _segment(start: int, end: int, text: str, *, ordinal: int = 1):
    return {
        "ordinal": ordinal,
        "speakerRole": "candidate",
        "rawSpeakerLabel": "我",
        "displayName": "候选人",
        "text": text,
        "sourceStart": start,
        "sourceEnd": end,
        "confidence": 0.9,
        "uncertaintyReason": None,
    }


def test_source_windows_are_bounded_and_overlap_for_context() -> None:
    windows = create_source_windows("字" * 50_000)

    assert [(item.source_start, item.source_end) for item in windows] == [
        (0, 24_000),
        (23_000, 47_000),
        (46_000, 50_000),
    ]
    assert all(len(item.body) <= 24_000 for item in windows)


def test_reducer_orders_by_source_offset_and_deduplicates_overlap() -> None:
    reduced = reduce_cleanup_segments(
        [
            [_segment(23_100, 23_120, "重复片段")],
            [
                _segment(23_100, 23_120, " 重复片段 "),
                _segment(24_000, 24_020, "后续片段", ordinal=2),
            ],
            [_segment(0, 10, "开头片段")],
        ]
    )

    assert [item["text"] for item in reduced] == [
        "开头片段",
        "重复片段",
        "后续片段",
    ]
    assert [item["ordinal"] for item in reduced] == [1, 2, 3]


def test_reducer_rejects_offset_regression_within_one_window() -> None:
    with pytest.raises(ValueError, match="offset"):
        reduce_cleanup_segments(
            [[_segment(10, 20, "后"), _segment(0, 5, "前", ordinal=2)]]
        )


def _cleanup_repository(tmp_path):
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
        workspace_id="w1",
        kind="interview.retrospective.chat",
        title="复盘讨论",
    )
    retrospective = service.create(
        job_target_id=target.id,
        title="示例公司后端一面",
        round_label="一面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        analysis_session_id=analysis.id,
        chat_session_id=chat.id,
        idempotency_key="create-retrospective",
    )
    source = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="字" * 50_000,
        file_name=None,
        idempotency_key="source-version",
    )
    return connection, repository, retrospective, source


def test_cleanup_work_items_resume_only_unfinished_windows(tmp_path) -> None:
    connection, repository, retrospective, source = _cleanup_repository(tmp_path)
    windows = create_source_windows(source.body)
    cleanup = repository.insert_cleanup_run(
        retrospective.id,
        source_version_id=source.id,
        input_digest=source.content_sha256,
        windows=windows,
    )

    items = repository.list_cleanup_work_items(cleanup.id)
    first = repository.claim_cleanup_work_item(items[0].id)
    repository.complete_cleanup_work_item(
        first.id,
        output={"segments": [_segment(0, 10, "开头片段")]},
    )

    pending = repository.list_resumable_cleanup_work_items(cleanup.id)
    assert cleanup.status == "queued"
    assert len(items) == 3
    assert [item.source_start for item in pending] == [23_000, 46_000]
    assert repository.list_cleanup_work_items(cleanup.id)[0].status == "completed"
    connection.close()


def test_stopping_cleanup_preserves_completed_window_output(tmp_path) -> None:
    connection, repository, retrospective, source = _cleanup_repository(tmp_path)
    cleanup = repository.insert_cleanup_run(
        retrospective.id,
        source_version_id=source.id,
        input_digest=source.content_sha256,
        windows=create_source_windows(source.body),
    )
    first = repository.claim_cleanup_work_item(
        repository.list_cleanup_work_items(cleanup.id)[0].id
    )
    repository.complete_cleanup_work_item(
        first.id,
        output={"segments": [_segment(0, 10, "已完成")]} ,
    )

    stopped = repository.stop_cleanup(cleanup.id)
    items = repository.list_cleanup_work_items(cleanup.id)

    assert stopped.status == "stopped"
    assert items[0].status == "completed"
    assert items[0].output is not None
    assert all(item.status == "interrupted" for item in items[1:])
    connection.close()


def test_reconcile_interrupted_execution_makes_cleanup_resumable(tmp_path) -> None:
    connection, repository, retrospective, source = _cleanup_repository(tmp_path)
    products = ProductRepository(connection)
    cleanup = repository.insert_cleanup_run(
        retrospective.id,
        source_version_id=source.id,
        input_digest=source.content_sha256,
        windows=create_source_windows(source.body),
    )
    execution = products.create_execution(
        retrospective.analysis_session_id,
        input={},
        model_bindings={},
    )
    repository.attach_cleanup_execution(cleanup.id, execution_id=execution.id)
    repository.claim_cleanup_work_item(
        repository.list_cleanup_work_items(cleanup.id)[0].id
    )
    products.interrupt_running()

    reconciled = repository.reconcile_interrupted_cleanup_runs()
    current = repository.get_cleanup_version(cleanup.id)

    assert reconciled == (cleanup.id,)
    assert current.status == "stopped"
    assert repository.list_cleanup_work_items(cleanup.id)[0].status == "interrupted"
    connection.close()
