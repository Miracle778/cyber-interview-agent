from __future__ import annotations

import json
from uuid import uuid4

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.interview_retrospectives.history_search import (
    HistoricalSearchService,
    RetrospectiveSearchFilters,
    RetrospectiveSearchPlan,
)
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository
from app.job_targets.repository import JobTargetRepository


def _add_corpus_item(
    connection,
    repository,
    products,
    *,
    workspace_id: str,
    title: str,
    lifecycle: str,
    origin: str,
    decision: str,
    question: str,
    answer: str,
):
    target = JobTargetRepository(connection).create_target(
        workspace_id=workspace_id,
        role_name="云原生开发",
        seniority="3-5 年",
        company_name="字节跳动",
        source_url=None,
    )
    analysis_session = products.create_session(
        workspace_id=workspace_id,
        kind="interview.retrospective.analysis",
        title="复盘分析",
        visibility="system",
    )
    chat_session = products.create_session(
        workspace_id=workspace_id,
        kind="interview.retrospective.chat",
        title="复盘讨论",
    )
    retrospective = repository.create_retrospective(
        workspace_id=workspace_id,
        job_target_id=target.id,
        title=title,
        round_label="技术二面",
        interview_date="2026-08-01",
        outcome="unrecorded",
        note="",
        analysis_session_id=analysis_session.id,
        chat_session_id=chat_session.id,
        create_idempotency_key=str(uuid4()),
    )
    source = repository.insert_source_version(
        retrospective.id,
        source_kind="transcript",
        file_name=None,
        body=answer,
        content_sha256=uuid4().hex * 2,
    )
    cleanup = repository.insert_cleanup_version(
        retrospective.id,
        source_version_id=source.id,
        input_digest=uuid4().hex * 2,
    )
    question_id = str(uuid4())
    run_id = str(uuid4())
    analysis_id = str(uuid4())
    connection.execute(
        "INSERT INTO interview_question_units("
        "id, retrospective_id, cleanup_version_id, stable_key, ordinal, "
        "question_kind, origin, question_text, decision_status, confidence) "
        "VALUES (?, ?, ?, ?, 1, 'system_design', ?, ?, ?, 0.9)",
        (question_id, retrospective.id, cleanup.id, question_id, origin, question, decision),
    )
    connection.execute(
        "INSERT INTO interview_analysis_runs("
        "id, retrospective_id, cleanup_version_id, input_digest, status, stage) "
        "VALUES (?, ?, ?, ?, 'completed', 'completed')",
        (run_id, retrospective.id, cleanup.id, uuid4().hex * 2),
    )
    connection.execute(
        "INSERT INTO interview_question_analyses("
        "id, analysis_run_id, question_unit_id, verdict, evidence_level, "
        "confidence, source_excerpt, result_status) "
        "VALUES (?, ?, ?, 'improvable', 'internal_evidence', 0.8, ?, 'formal')",
        (analysis_id, run_id, question_id, answer),
    )
    connection.execute(
        "UPDATE interview_retrospectives SET active_analysis_run_id = ?, "
        "lifecycle_status = ? WHERE id = ?",
        (run_id, lifecycle, retrospective.id),
    )
    connection.commit()
    return retrospective, question_id


def test_search_filters_corpus_and_freezes_explainable_ranking(tmp_path) -> None:
    connection = connect_runtime_database(tmp_path)
    products = ProductRepository(connection)
    repository = InterviewRetrospectiveRepository(connection)
    expected, expected_question = _add_corpus_item(
        connection,
        repository,
        products,
        workspace_id="w1",
        title="数字签名云服务复盘",
        lifecycle="active",
        origin="original",
        decision="confirmed",
        question="数字签名系统为什么要对接 PKI 和 HSM？",
        answer="候选人解释了证书、私钥和签名服务的调用链。",
    )
    _add_corpus_item(
        connection,
        repository,
        products,
        workspace_id="w1",
        title="未确认推断题",
        lifecycle="active",
        origin="inferred",
        decision="pending",
        question="PKI 的职责是什么？",
        answer="不应进入语料。",
    )
    _add_corpus_item(
        connection,
        repository,
        products,
        workspace_id="w1",
        title="回收站复盘",
        lifecycle="recycled",
        origin="original",
        decision="confirmed",
        question="HSM 是什么？",
        answer="不应进入语料。",
    )
    _add_corpus_item(
        connection,
        repository,
        products,
        workspace_id="w2",
        title="其他工作区",
        lifecycle="active",
        origin="original",
        decision="confirmed",
        question="数字签名系统如何工作？",
        answer="不应跨工作区。",
    )

    outcome = HistoricalSearchService(repository).search(
        workspace_id="w1",
        query_text="帮我找一下之前关于数字签名项目的问题",
        plan=RetrospectiveSearchPlan(
            terms=("数字签名", "PKI", "HSM"),
            project_aliases=("签名云服务",),
        ),
        filters=RetrospectiveSearchFilters(company="字节"),
    )

    assert outcome.search_set.total_questions == 1
    assert outcome.search_set.total_retrospectives == 1
    assert outcome.items[0].retrospective_id == expected.id
    assert outcome.items[0].question_unit_id == expected_question
    assert set(outcome.items[0].matched_terms) >= {"数字签名", "PKI", "HSM"}
    assert json.loads(
        connection.execute(
            "SELECT search_plan_json FROM interview_retrospective_search_sets "
            "WHERE id = ?",
            (outcome.search_set.id,),
        ).fetchone()[0]
    )["effectiveTerms"] == ["数字签名", "PKI", "HSM", "签名云服务"]
    connection.close()
