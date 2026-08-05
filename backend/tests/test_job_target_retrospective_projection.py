from __future__ import annotations

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository
from app.interview_retrospectives.service import InterviewRetrospectiveService
from app.job_targets.repository import JobTargetRepository


def _sessions(products: ProductRepository, suffix: str):
    analysis = products.create_session(
        workspace_id="w1",
        kind="interview.retrospective.analysis",
        title=f"分析 {suffix}",
        visibility="system",
    )
    chat = products.create_session(
        workspace_id="w1",
        kind="interview.retrospective.chat",
        title=f"讨论 {suffix}",
    )
    return analysis, chat


def test_target_summary_aggregates_only_the_selected_target(tmp_path) -> None:
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
    other = targets.create_target(
        workspace_id="w1",
        role_name="前端工程师",
        seniority="3-5 年",
        company_name="另一家公司",
        source_url=None,
    )

    created = []
    for index, (target_id, date, round_label, outcome) in enumerate(
        (
            (target.id, "2026-07-20", "一面", "failed"),
            (target.id, "2026-08-01", "二面", "passed"),
            (other.id, "2026-08-02", "一面", "failed"),
        ),
        start=1,
    ):
        analysis, chat = _sessions(products, str(index))
        created.append(
            service.create(
                job_target_id=target_id,
                title=f"复盘 {index}",
                round_label=round_label,
                interview_date=date,
                outcome=outcome,
                note="",
                analysis_session_id=analysis.id,
                chat_session_id=chat.id,
                idempotency_key=f"summary-{index}",
            )
        )

    # The dashboard must use only the active run of each retrospective and must
    # not leak report bodies or numeric quality scores.
    for retrospective, suffix in ((created[0], "old"), (created[1], "latest")):
        connection.execute(
            "INSERT INTO interview_source_versions("
            "id, retrospective_id, ordinal, source_kind, body, content_sha256) "
            "VALUES (?, ?, 1, 'recollection', '正文', ?)",
            (f"source-{suffix}", retrospective.id, suffix[0] * 64),
        )
        connection.execute(
            "INSERT INTO interview_cleanup_versions("
            "id, retrospective_id, source_version_id, ordinal, input_digest, status, stage) "
            "VALUES (?, ?, ?, 1, ?, 'confirmed', 'confirmed')",
            (f"cleanup-{suffix}", retrospective.id, f"source-{suffix}", suffix[-1] * 64),
        )
    connection.execute(
        "INSERT INTO interview_analysis_runs("
        "id, retrospective_id, cleanup_version_id, input_digest) "
        "VALUES ('run-old', ?, 'cleanup-old', ?)",
        (created[0].id, "a" * 64),
    )
    connection.execute(
        "INSERT INTO interview_analysis_runs("
        "id, retrospective_id, cleanup_version_id, input_digest) "
        "VALUES ('run-latest', ?, 'cleanup-latest', ?)",
        (created[1].id, "b" * 64),
    )
    connection.execute(
        "UPDATE interview_retrospectives SET active_analysis_run_id = CASE id "
        "WHEN ? THEN 'run-old' WHEN ? THEN 'run-latest' END WHERE id IN (?, ?)",
        (created[0].id, created[1].id, created[0].id, created[1].id),
    )
    for suffix, ordinal, run_id, retrospective_id, kind in (
        ("1", 1, "run-old", created[0].id, "knowledge"),
        ("2", 1, "run-latest", created[1].id, "knowledge"),
        ("3", 2, "run-latest", created[1].id, "expression"),
    ):
        connection.execute(
            "INSERT INTO interview_question_units("
            "id, retrospective_id, cleanup_version_id, stable_key, ordinal, "
            "question_kind, origin, question_text, inference_basis, confidence) "
            "VALUES (?, ?, ?, ?, ?, 'technical_knowledge', 'original', '题目', '', 1)",
            (f"q-{suffix}", retrospective_id, f"cleanup-{'old' if run_id == 'run-old' else 'latest'}", f"q-{suffix}", ordinal),
        )
        connection.execute(
            "INSERT INTO interview_question_analyses("
            "id, analysis_run_id, question_unit_id, verdict, evidence_level, confidence) "
            "VALUES (?, ?, ?, 'improvable', 'model_judgment', 0.8)",
            (f"qa-{suffix}", run_id, f"q-{suffix}"),
        )
        connection.execute(
            "INSERT INTO interview_gaps("
            "id, analysis_run_id, question_analysis_id, question_unit_id, gap_kind, summary) "
            "VALUES (?, ?, ?, ?, ?, '重复短板')",
            (f"gap-{suffix}", run_id, f"qa-{suffix}", f"q-{suffix}", kind),
        )
    connection.execute(
        "INSERT INTO interview_action_items("
        "id, retrospective_id, analysis_run_id, action_kind, title, status) "
        "VALUES ('action-pending', ?, 'run-latest', 'knowledge', '补齐知识', 'pending')",
        (created[1].id,),
    )
    connection.commit()

    summary = service.target_summary(target.id)

    assert summary["retrospectiveCount"] == 2
    assert summary["latest"] == {
        "retrospectiveId": created[1].id,
        "title": "复盘 2",
        "roundLabel": "二面",
        "interviewDate": "2026-08-01",
        "outcome": "passed",
        "lifecycleStatus": "active",
    }
    assert summary["unresolvedActionCount"] == 1
    assert summary["gapCounts"] == {"knowledge": 2, "expression": 1}
    assert len(summary["timeline"]) == 2
    assert "score" not in str(summary).lower()
    assert "suggested" not in str(summary).lower()
    connection.close()


def test_target_summary_rejects_a_target_from_another_workspace(tmp_path) -> None:
    connection = connect_runtime_database(tmp_path)
    targets = JobTargetRepository(connection)
    target = targets.create_target(
        workspace_id="w2",
        role_name="后端工程师",
        seniority="",
        company_name=None,
        source_url=None,
    )
    service = InterviewRetrospectiveService(
        workspace_id="w1",
        repository=InterviewRetrospectiveRepository(connection),
        job_targets=targets,
    )

    from app.interview_retrospectives.errors import RetrospectiveTargetRequired
    import pytest

    with pytest.raises(RetrospectiveTargetRequired):
        service.target_summary(target.id)
    connection.close()
