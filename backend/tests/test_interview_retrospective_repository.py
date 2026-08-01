from __future__ import annotations

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository
from app.job_targets.repository import JobTargetRepository


def test_repository_lists_only_the_current_workspace(tmp_path) -> None:
    connection = connect_runtime_database(tmp_path)
    products = ProductRepository(connection)
    targets = JobTargetRepository(connection)
    first_target = targets.create_target(
        workspace_id="w1",
        role_name="后端工程师",
        seniority="3-5 年",
        company_name="甲公司",
        source_url=None,
    )
    second_target = targets.create_target(
        workspace_id="w2",
        role_name="平台工程师",
        seniority="5-8 年",
        company_name="乙公司",
        source_url=None,
    )
    repository = InterviewRetrospectiveRepository(connection)

    for workspace_id, target in (("w1", first_target), ("w2", second_target)):
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
        repository.create_retrospective(
            workspace_id=workspace_id,
            job_target_id=target.id,
            title=f"{target.role_name}一面复盘",
            round_label="一面",
            interview_date=None,
            outcome="unrecorded",
            note="",
            analysis_session_id=analysis.id,
            chat_session_id=chat.id,
            create_idempotency_key=f"create-{workspace_id}",
        )

    rows = repository.list_retrospectives(
        workspace_id="w1", lifecycle_status="active"
    )

    assert len(rows) == 1
    assert rows[0].workspace_id == "w1"
    assert rows[0].job_target_id == first_target.id
    connection.close()
