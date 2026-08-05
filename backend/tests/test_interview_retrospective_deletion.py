from __future__ import annotations

import pytest

from app.application.session_service import ProductRepository
from app.interview_retrospectives.errors import RetrospectiveBusy, RetrospectiveNotFound
from tests.interview_retrospective_candidate_helpers import candidate_fixture


def test_permanent_delete_removes_private_records_but_keeps_external_receipt_target(tmp_path) -> None:
    connection, application, retrospective, run, questions = candidate_fixture(tmp_path)
    connection.execute(
        "INSERT INTO interview_asset_candidates("
        "id, retrospective_id, analysis_run_id, question_unit_id, candidate_kind, "
        "fingerprint, payload_json, status, target_resource_type, target_resource_id) "
        "VALUES ('candidate-external', ?, ?, ?, 'review_question', 'candidate-fp', '{}', "
        "'confirmed', 'job_target', ?)",
        (retrospective.id, run.id, questions[0].id, retrospective.job_target_id),
    )
    connection.commit()
    current = application.get_retrospective(retrospective.id)
    recycled = application.recycle(
        retrospective.id,
        expected_version=current.version,
        idempotency_key="delete-recycle",
    )

    application.delete_permanently(
        retrospective.id,
        expected_version=recycled.version,
        idempotency_key="delete-private",
    )

    with pytest.raises(RetrospectiveNotFound):
        application.get_retrospective(retrospective.id)
    assert connection.execute(
        "SELECT COUNT(*) FROM job_targets WHERE id = ?",
        (retrospective.job_target_id,),
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM interview_asset_candidates WHERE retrospective_id = ?",
        (retrospective.id,),
    ).fetchone()[0] == 0
    connection.close()


def test_active_chat_run_blocks_permanent_delete(tmp_path) -> None:
    connection, application, retrospective, _, _ = candidate_fixture(tmp_path)
    current = application.get_retrospective(retrospective.id)
    recycled = application.recycle(
        retrospective.id,
        expected_version=current.version,
        idempotency_key="busy-delete-recycle",
    )
    ProductRepository(connection).create_execution(
        retrospective.chat_session_id,
        input={"retrospectiveId": retrospective.id},
        model_bindings={},
    )

    with pytest.raises(RetrospectiveBusy):
        application.delete_permanently(
            retrospective.id,
            expected_version=recycled.version,
            idempotency_key="busy-delete",
        )
    connection.close()
