from __future__ import annotations

import pytest

from app.application.session_service import ProductRepository
from app.interview_retrospectives.errors import RetrospectiveBusy, RetrospectiveSourceCleared
from tests.interview_retrospective_candidate_helpers import candidate_fixture


def test_clear_source_removes_all_recoverable_excerpts_and_blocks_reanalysis(tmp_path) -> None:
    connection, application, retrospective, run, questions = candidate_fixture(tmp_path)
    before = application.get_retrospective(retrospective.id)
    search = application.repository.create_search_set(
        workspace_id=retrospective.workspace_id,
        query_text="历史问题",
        filters={},
        search_plan={"terms": ["问题"]},
    )
    application.repository.replace_search_results(
        search.id,
        results=(
            {
                "retrospective_id": retrospective.id,
                "question_unit_id": questions[0].id,
                "score": 8,
                "matched_terms": ("问题",),
                "question_snapshot": {"questionText": questions[0].question_text},
                "answer_excerpt": "这是可恢复的原回答证据",
                "analysis_snapshot": {},
            },
        ),
    )

    cleared = application.clear_source(
        retrospective.id,
        before.active_source_version_id,
        expected_version=before.version,
        idempotency_key="clear-source-task-10",
    )

    assert cleared.body == ""
    assert cleared.cleared_at is not None
    assert all(item.source_excerpt == "" and not item.source_available for item in application.repository.list_question_analyses(run.id))
    assert all(segment.body == "" for segment in application.repository.list_segments(before.active_cleanup_version_id))
    search_result = application.repository.list_search_results(search.id)[0]
    assert search_result.answer_excerpt == ""
    assert not search_result.source_available
    with pytest.raises(RetrospectiveSourceCleared):
        application.service.create_analysis_run(
            retrospective.id,
            before.active_cleanup_version_id,
            input_digest="c" * 64,
            context_snapshot={},
            idempotency_key="reanalyze-cleared",
        )
    connection.close()


def test_active_execution_blocks_source_clear(tmp_path) -> None:
    connection, application, retrospective, _, _ = candidate_fixture(tmp_path)
    products = ProductRepository(connection)
    products.create_execution(
        retrospective.analysis_session_id,
        input={"retrospectiveId": retrospective.id},
        model_bindings={},
    )
    current = application.get_retrospective(retrospective.id)

    with pytest.raises(RetrospectiveBusy):
        application.clear_source(
            retrospective.id,
            current.active_source_version_id,
            expected_version=current.version,
            idempotency_key="clear-source-busy",
        )
    connection.close()
