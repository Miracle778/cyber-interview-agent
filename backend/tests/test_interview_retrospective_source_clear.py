from __future__ import annotations

import pytest

from app.application.session_service import ProductRepository
from app.interview_retrospectives.errors import RetrospectiveBusy, RetrospectiveSourceCleared
from tests.interview_retrospective_candidate_helpers import candidate_fixture


def test_clear_source_removes_all_recoverable_excerpts_and_blocks_reanalysis(tmp_path) -> None:
    connection, application, retrospective, run, questions = candidate_fixture(tmp_path)
    before = application.get_retrospective(retrospective.id)

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
