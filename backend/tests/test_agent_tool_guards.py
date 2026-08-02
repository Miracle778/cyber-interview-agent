from dataclasses import replace

from app.agents.context import AgentContext
from app.tools.interview_retrospective_tools import (
    RETROSPECTIVE_TOOL_NAMES,
    RETROSPECTIVE_TOOL_SCOPE,
    read_question_analysis,
    read_source_excerpt,
    read_retrospective_summary,
)
from interview_retrospective_candidate_helpers import candidate_fixture


def _context(tmp_path, retrospective_id: str | None) -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="session",
        run_id="run",
        allowed_tools=frozenset(RETROSPECTIVE_TOOL_NAMES),
        allowed_scopes=frozenset({RETROSPECTIVE_TOOL_SCOPE}),
        retrospective_id=retrospective_id,
        tool_result_item_limit=20,
        tool_excerpt_char_limit=8,
    )


def test_retrospective_tools_require_server_context(tmp_path) -> None:
    connection, application, _retrospective, _run, _questions = candidate_fixture(
        tmp_path
    )

    result = read_retrospective_summary(
        application.repository, _context(tmp_path, None)
    )

    assert result["errorCode"] == "retrospective_context_required"
    connection.close()


def test_retrospective_tools_reject_question_from_other_retrospective(tmp_path) -> None:
    connection, application, retrospective, _run, questions = candidate_fixture(
        tmp_path
    )
    context = replace(_context(tmp_path, retrospective.id), retrospective_id="other")

    result = read_question_analysis(
        application.repository, context, question_id=questions[0].id
    )

    assert result["errorCode"] == "question_context_mismatch"
    missing = read_question_analysis(
        application.repository,
        _context(tmp_path, retrospective.id),
        question_id="arbitrary-question-id",
    )
    assert missing["errorCode"] == "question_context_mismatch"
    connection.close()


def test_source_excerpt_is_bounded_and_accepts_no_path(tmp_path) -> None:
    connection, application, retrospective, _run, questions = candidate_fixture(
        tmp_path
    )

    result = read_source_excerpt(
        application.repository,
        _context(tmp_path, retrospective.id),
        question_id=questions[0].id,
    )

    assert result["status"] == "ok"
    assert all(len(item["body"].rstrip("…")) <= 8 for item in result["items"])
    assert "path" not in str(result)
    connection.close()


def test_retrospective_summary_stays_in_current_workspace(tmp_path) -> None:
    connection, application, retrospective, _run, _questions = candidate_fixture(
        tmp_path
    )

    result = read_retrospective_summary(
        application.repository,
        replace(_context(tmp_path, retrospective.id), workspace_id="w2"),
    )

    assert result["errorCode"] == "retrospective_context_mismatch"
    connection.close()
