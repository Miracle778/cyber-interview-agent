from __future__ import annotations

import json

from app.evaluation.outcome_adapters.domain import create_sqlite_outcome_adapter
from app.evaluation.registry import get_eval_pack
from app.evaluation.views import build_task_evaluation_view
from app.infrastructure.runtime_database import connect_runtime_database


def _seed_retrospective(connection) -> None:
    connection.execute(
        "INSERT INTO job_targets "
        "(id, workspace_id, company_name, role_name, seniority) "
        "VALUES ('target-1', 'workspace-1', '字节跳动', '云原生开发', '高级')"
    )
    for session_id in ("analysis-session", "chat-session", "history-session"):
        connection.execute(
            "INSERT INTO agent_sessions "
            "(id, workspace_id, graph_id, graph_version, title) "
            "VALUES (?, 'workspace-1', 'interview.retrospective', 1, '面试复盘')",
            (session_id,),
        )
    connection.execute(
        "INSERT INTO interview_retrospectives "
        "(id, workspace_id, job_target_id, title, round_label, "
        "analysis_session_id, chat_session_id, create_idempotency_key) "
        "VALUES ('retro-1', 'workspace-1', 'target-1', '字节云', '二面', "
        "'analysis-session', 'chat-session', 'create-1')"
    )
    connection.execute(
        "INSERT INTO interview_source_versions "
        "(id, retrospective_id, ordinal, source_kind, body, content_sha256) "
        "VALUES ('source-1', 'retro-1', 1, 'transcript', ?, ?)",
        ("面试官：介绍项目。候选人：我参与了数字签名服务。", "a" * 64),
    )


def _insert_run(connection, execution_id: str, session_id: str) -> None:
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status, input_json) "
        "VALUES (?, ?, 'completed', '{}')",
        (execution_id, session_id),
    )


def _applicability(view) -> dict[str, str]:
    return {item.dimension_id: item.applicability for item in view.dimensions}


def test_cleanup_projection_keeps_source_and_only_enables_cleanup_dimensions(
    tmp_path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        _seed_retrospective(connection)
        _insert_run(connection, "cleanup-execution", "analysis-session")
        connection.execute(
            "INSERT INTO interview_cleanup_versions "
            "(id, retrospective_id, source_version_id, ordinal, execution_id, "
            "input_digest, status, stage, confirmed_at) "
            "VALUES ('cleanup-1', 'retro-1', 'source-1', 1, 'cleanup-execution', "
            "?, 'confirmed', 'confirmed', CURRENT_TIMESTAMP)",
            ("b" * 64,),
        )
        connection.execute(
            "INSERT INTO interview_cleanup_work_items "
            "(id, cleanup_version_id, work_key, source_start, source_end, "
            "input_digest, status) "
            "VALUES ('cleanup-work-1', 'cleanup-1', 'window-1', 0, 12, ?, 'completed')",
            ("c" * 64,),
        )
        connection.execute(
            "INSERT INTO interview_segments "
            "(id, cleanup_version_id, ordinal, speaker_role, display_name, body, "
            "source_start, source_end, confidence, uncertainty_reason) "
            "VALUES ('segment-1', 'cleanup-1', 1, 'unknown', '待确认', "
            "'介绍一下项目', 0, 7, 0.55, '仅录到候选人一侧')"
        )
        connection.commit()

        outcome = create_sqlite_outcome_adapter(
            "interview_retrospective", connection, "workspace-1"
        ).build("cleanup-execution")
        view = build_task_evaluation_view(
            outcome, get_eval_pack("interview-retrospective.v2")
        )
        dimensions = _applicability(view)

        assert outcome.input.requested_scope["mode"] == "cleanup"
        assert outcome.items[0].content["text"] == "介绍一下项目"
        assert outcome.items[0].content["speaker_role"] == "unknown"
        assert outcome.items[0].provenance[0].source_refs == (
            "source:source-1:0-7",
        )
        assert dimensions["transcript_fidelity"] == "applicable"
        assert dimensions["uncertainty_confirmation"] == "applicable"
        assert dimensions["question_extraction_completeness"] == "not_applicable"
        assert dimensions["discussion_context"] == "not_applicable"
    finally:
        connection.close()


def test_analysis_projection_preserves_inferred_question_decision_and_evidence(
    tmp_path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        _seed_retrospective(connection)
        _insert_run(connection, "analysis-execution", "analysis-session")
        connection.execute(
            "INSERT INTO interview_cleanup_versions "
            "(id, retrospective_id, source_version_id, ordinal, input_digest, status, stage) "
            "VALUES ('cleanup-1', 'retro-1', 'source-1', 1, ?, 'confirmed', 'confirmed')",
            ("b" * 64,),
        )
        connection.execute(
            "INSERT INTO interview_analysis_runs "
            "(id, retrospective_id, cleanup_version_id, execution_id, input_digest, "
            "status, stage, completed_items, total_items) "
            "VALUES ('analysis-1', 'retro-1', 'cleanup-1', 'analysis-execution', ?, "
            "'completed', 'completed', 1, 1)",
            ("d" * 64,),
        )
        connection.execute(
            "INSERT INTO interview_question_units "
            "(id, retrospective_id, cleanup_version_id, stable_key, ordinal, "
            "question_kind, origin, question_text, inference_basis, confidence, decision_status) "
            "VALUES ('question-1', 'retro-1', 'cleanup-1', 'q-1', 1, "
            "'project_experience', 'inferred', '你负责什么工作？', "
            "'候选人开始介绍职责', 0.65, 'pending')"
        )
        connection.execute(
            "INSERT INTO interview_analysis_work_items "
            "(id, analysis_run_id, question_unit_id, work_key, input_digest, status) "
            "VALUES ('analysis-work-1', 'analysis-1', 'question-1', 'q-1', ?, 'completed')",
            ("e" * 64,),
        )
        connection.execute(
            "INSERT INTO interview_question_analyses "
            "(id, analysis_run_id, question_unit_id, verdict, strengths_json, "
            "improvements_json, omissions_json, evidence_level, confidence, "
            "improvement_outline_json, suggested_answer, source_excerpt, "
            "source_excerpt_sha256, result_status) "
            "VALUES ('qa-1', 'analysis-1', 'question-1', 'improvable', '[]', "
            "?, '[]', 'internal_evidence', 0.8, ?, '补充职责边界', "
            "'我参与了数字签名服务', ?, 'formal')",
            (
                json.dumps(["没有说明个人职责"], ensure_ascii=False),
                json.dumps(["先讲职责，再讲方案"], ensure_ascii=False),
                "f" * 64,
            ),
        )
        connection.commit()

        outcome = create_sqlite_outcome_adapter(
            "interview_retrospective", connection, "workspace-1"
        ).build("analysis-execution")
        view = build_task_evaluation_view(
            outcome, get_eval_pack("interview-retrospective.v2")
        )
        dimensions = _applicability(view)

        assert outcome.input.requested_scope["mode"] == "analysis"
        assert outcome.items[0].content["inferred"] is True
        assert outcome.items[0].user_decision.status == "pending"
        assert outcome.items[0].content["evidence"] == "我参与了数字签名服务"
        assert dimensions["question_extraction_completeness"] == "applicable"
        assert dimensions["analysis_grounding"] == "applicable"
        assert dimensions["recommendation_actionability"] == "applicable"
        assert dimensions["transcript_fidelity"] == "not_applicable"
    finally:
        connection.close()


def test_chat_projection_does_not_turn_messages_into_formal_analysis(tmp_path) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        _seed_retrospective(connection)
        _insert_run(connection, "chat-execution", "chat-session")
        connection.execute(
            "INSERT INTO agent_messages "
            "(id, session_id, run_id, role, content, message_kind, resolution_status) "
            "VALUES ('message-1', 'chat-session', 'chat-execution', 'user', "
            "'这道题哪里答得不好？', 'text', 'active')"
        )
        connection.execute(
            "INSERT INTO agent_messages "
            "(id, session_id, run_id, role, content, message_kind, resolution_status) "
            "VALUES ('message-2', 'chat-session', 'chat-execution', 'assistant', "
            "'职责和结果说得不够具体。', 'text', 'active')"
        )
        connection.commit()

        outcome = create_sqlite_outcome_adapter(
            "interview_retrospective", connection, "workspace-1"
        ).build("chat-execution")
        view = build_task_evaluation_view(
            outcome, get_eval_pack("interview-retrospective.v2")
        )
        dimensions = _applicability(view)

        assert outcome.input.requested_scope["mode"] == "discussion"
        assert {item.item_type for item in outcome.items} == {"discussion_message"}
        assert dimensions["discussion_context"] == "applicable"
        assert dimensions["analysis_grounding"] == "not_applicable"
        assert dimensions["history_source_coverage"] == "not_applicable"
    finally:
        connection.close()


def test_history_projection_keeps_search_match_sources(tmp_path) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        _seed_retrospective(connection)
        _insert_run(connection, "history-execution", "history-session")
        connection.execute(
            "INSERT INTO interview_retrospective_search_sets "
            "(id, workspace_id, session_id, execution_id, query_text, status, "
            "total_questions, total_retrospectives) "
            "VALUES ('search-1', 'workspace-1', 'history-session', 'history-execution', "
            "'数字签名项目', 'completed', 1, 1)"
        )
        connection.execute(
            "INSERT INTO interview_retrospective_search_results "
            "(id, search_set_id, retrospective_id, rank, score, source_metadata_json, "
            "question_snapshot_json, answer_excerpt, analysis_snapshot_json) "
            "VALUES ('match-1', 'search-1', 'retro-1', 1, 0.9, '{}', "
            "?, '我参与了数字签名服务', '{}')",
            (json.dumps({"questionText": "数字签名项目做了什么？"}, ensure_ascii=False),),
        )
        connection.commit()

        outcome = create_sqlite_outcome_adapter(
            "interview_retrospective", connection, "workspace-1"
        ).build("history-execution")
        view = build_task_evaluation_view(
            outcome, get_eval_pack("interview-retrospective.v2")
        )
        dimensions = _applicability(view)

        assert outcome.input.requested_scope["mode"] == "history"
        assert outcome.items[0].content["query"] == "数字签名项目"
        assert outcome.items[0].provenance[0].source_refs == (
            "retrospective:retro-1",
            "search-result:match-1",
        )
        assert dimensions["history_source_coverage"] == "applicable"
        assert dimensions["discussion_context"] == "not_applicable"
    finally:
        connection.close()
