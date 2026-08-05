from __future__ import annotations

from uuid import uuid4

import pytest

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.interview_retrospectives.errors import (
    RetrospectiveNotFound,
    RetrospectiveVersionConflict,
)
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository
from app.job_targets.repository import JobTargetRepository


def _retrospective_fixture(tmp_path, *, workspace_id: str = "w1"):
    connection = connect_runtime_database(tmp_path)
    products = ProductRepository(connection)
    target = JobTargetRepository(connection).create_target(
        workspace_id=workspace_id,
        role_name="云原生开发",
        seniority="3-5 年",
        company_name="字节跳动",
        source_url=None,
    )
    analysis = products.create_session(
        workspace_id=workspace_id,
        kind="interview.retrospective.analysis",
        title="复盘分析",
        visibility="system",
    )
    chat = products.create_session(
        workspace_id=workspace_id,
        kind="interview.retrospective.chat",
        title="复盘讨论",
    )
    repository = InterviewRetrospectiveRepository(connection)
    retrospective = repository.create_retrospective(
        workspace_id=workspace_id,
        job_target_id=target.id,
        title="字节跳动技术二面",
        round_label="技术二面",
        interview_date="2025-12-24",
        outcome="unrecorded",
        note="",
        analysis_session_id=analysis.id,
        chat_session_id=chat.id,
        create_idempotency_key=str(uuid4()),
    )
    source = repository.insert_source_version(
        retrospective.id,
        source_kind="transcript",
        file_name="round.md",
        body="面试官问数字签名架构。",
        content_sha256="a" * 64,
    )
    cleanup = repository.insert_cleanup_version(
        retrospective.id,
        source_version_id=source.id,
        input_digest="b" * 64,
    )
    question_id = str(uuid4())
    connection.execute(
        "INSERT INTO interview_question_units("
        "id, retrospective_id, cleanup_version_id, stable_key, ordinal, "
        "question_kind, origin, question_text, decision_status, confidence) "
        "VALUES (?, ?, ?, ?, 1, 'system_design', 'original', ?, 'confirmed', 0.9)",
        (
            question_id,
            retrospective.id,
            cleanup.id,
            "question-1",
            "数字签名系统的整体架构是怎样的？",
        ),
    )
    connection.commit()
    return connection, repository, retrospective, question_id


def test_search_set_freezes_ordered_workspace_results(tmp_path) -> None:
    connection, repository, retrospective, question_id = _retrospective_fixture(
        tmp_path
    )
    search = repository.create_search_set(
        workspace_id="w1",
        query_text="数字签名项目",
        filters={"jobTargetId": retrospective.job_target_id},
        search_plan={"terms": ["数字签名", "PKI"]},
    )

    results = repository.replace_search_results(
        search.id,
        results=(
            {
                "retrospective_id": retrospective.id,
                "question_unit_id": question_id,
                "score": 12.0,
                "matched_terms": ("数字签名",),
                "source_metadata": {"companyName": "字节跳动"},
                "question_snapshot": {
                    "questionText": "数字签名系统的整体架构是怎样的？"
                },
                "answer_excerpt": "签名服务与证书管理共同组成系统。",
                "analysis_snapshot": {"verdict": "improvable"},
            },
        ),
    )

    refreshed = repository.get_search_set(search.id, workspace_id="w1")
    assert refreshed.status == "completed"
    assert refreshed.total_questions == 1
    assert refreshed.total_retrospectives == 1
    assert results[0].rank == 1
    assert results[0].matched_terms == ("数字签名",)
    assert results[0].question_snapshot["questionText"].startswith("数字签名")
    connection.close()


def test_search_sets_can_be_restored_in_recent_order_and_stay_workspace_scoped(
    tmp_path,
) -> None:
    connection, repository, retrospective, _ = _retrospective_fixture(tmp_path)
    first = repository.create_search_set(
        workspace_id="w1",
        query_text="第一次检索",
        filters={"jobTargetId": retrospective.job_target_id},
        search_plan={"terms": ["第一次"]},
    )
    second = repository.create_search_set(
        workspace_id="w1",
        query_text="第二次检索",
        filters={},
        search_plan={"terms": ["第二次"]},
    )
    repository.create_search_set(
        workspace_id="other-workspace",
        query_text="其他工作区",
        filters={},
        search_plan={"terms": ["其他"]},
    )

    restored = repository.list_search_sets(workspace_id="w1", limit=10)

    assert [item.id for item in restored] == [second.id, first.id]
    connection.close()


def test_search_set_and_report_are_workspace_scoped(tmp_path) -> None:
    connection, repository, _retrospective, _question_id = _retrospective_fixture(
        tmp_path
    )
    search = repository.create_search_set(
        workspace_id="w1",
        query_text="PKI",
        filters={},
        search_plan={"terms": ["PKI"]},
    )
    with pytest.raises(RetrospectiveNotFound):
        repository.get_search_set(search.id, workspace_id="w2")

    report = repository.create_search_report(
        workspace_id="w1",
        search_set_id=search.id,
        title="数字签名专项复盘",
        focus="preparation",
        selected_result_ids=(),
        include_answer_excerpts=True,
        include_action_plan=True,
    )
    assert report.ordinal == 1
    assert repository.list_search_reports(workspace_id="w1") == (report,)
    with pytest.raises(RetrospectiveNotFound):
        repository.get_search_report(report.id, workspace_id="w2")
    connection.close()


def test_completed_search_report_uses_optimistic_edit_version(tmp_path) -> None:
    connection, repository, _retrospective, _question_id = _retrospective_fixture(
        tmp_path
    )
    search = repository.create_search_set(
        workspace_id="w1",
        query_text="PKI",
        filters={},
        search_plan={"terms": ["PKI"]},
    )
    report = repository.create_search_report(
        workspace_id="w1",
        search_set_id=search.id,
        title="数字签名专项复盘",
        focus="preparation",
        selected_result_ids=(),
        include_answer_excerpts=True,
        include_action_plan=True,
    )
    completed = repository.complete_search_report(
        report.id,
        title=report.title,
        body={"sections": []},
        markdown="# 初稿",
        citation_question_ids=(),
    )

    edited = repository.update_search_report(
        report.id,
        workspace_id="w1",
        expected_version=completed.version,
        title="数字签名面试总结",
        markdown="# 用户修订稿",
    )

    assert edited.markdown == "# 用户修订稿"
    assert edited.version == completed.version + 1
    with pytest.raises(RetrospectiveVersionConflict):
        repository.update_search_report(
            report.id,
            workspace_id="w1",
            expected_version=completed.version,
            title="过期修改",
            markdown="不能覆盖",
        )
    connection.close()
