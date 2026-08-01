from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_agent_application
from app.main import app as api_app

from interview_retrospective_candidate_helpers import candidate_fixture


class FakeReview:
    def __init__(self, *, workspace_id: str = "w1") -> None:
        self.workspace_id = workspace_id
        self.created = 0
        self._catalog = (
            SimpleNamespace(
                workspace_id=workspace_id,
                snapshot=SimpleNamespace(
                    question_id="review-existing",
                    question_text="请问如何治理缓存一致性？",
                    topics=("缓存",),
                ),
            ),
        )

    def list_questions(self):
        return self._catalog

    def get_confirmed_question(self, question_id: str):
        if question_id != "review-existing":
            raise LookupError(question_id)
        return self._catalog[0]

    async def create_retrospective_candidate(self, **values):
        self.created += 1
        return SimpleNamespace(id=f"review-proposal-{self.created}")


class FailingReview(FakeReview):
    async def create_retrospective_candidate(self, **values):
        del values
        raise RuntimeError("review unavailable")


def test_generation_excludes_pending_inferred_and_returns_review_matches(tmp_path):
    connection, app, retrospective, run, questions = candidate_fixture(
        tmp_path, review=FakeReview()
    )

    candidates = app.generate_candidates(retrospective.id, run.id)

    review = [item for item in candidates if item.candidate_kind == "review_question"]
    assert len(review) == 1
    assert review[0].question_unit_id == questions[0].id
    assert questions[1].id not in review[0].payload_json
    assert "review-existing" in review[0].match_json
    assert {item.candidate_kind for item in candidates} == {
        "review_question",
        "summary",
    }
    assert len(app.list_actions(retrospective.id)) == 1
    connection.close()


def test_rejected_fingerprint_is_not_reproposed(tmp_path):
    connection, app, retrospective, run, _questions = candidate_fixture(tmp_path)
    candidate = next(
        item
        for item in app.generate_candidates(retrospective.id, run.id)
        if item.candidate_kind == "review_question"
    )
    rejected = app.repository.transition_asset_candidate(
        candidate.id,
        status="rejected",
        target_resource_type=None,
        target_resource_id=None,
        last_error_code=None,
        expected_version=candidate.version,
    )

    regenerated = app.generate_candidates(retrospective.id, run.id)

    same = next(item for item in regenerated if item.id == rejected.id)
    assert same.status == "rejected"
    assert (
        len([item for item in regenerated if item.candidate_kind == "review_question"])
        == 1
    )
    connection.close()


@pytest.mark.asyncio
async def test_candidate_decision_is_receipted_and_rejects_cross_workspace_target(
    tmp_path,
):
    review = FakeReview()
    connection, app, retrospective, run, _questions = candidate_fixture(
        tmp_path, review=review
    )
    candidate = next(
        item
        for item in app.generate_candidates(retrospective.id, run.id)
        if item.candidate_kind == "review_question"
    )

    first = await app.decide_candidate(
        retrospective.id,
        candidate.id,
        action="create_new",
        target_resource_id=None,
        action_payload={},
        expected_version=candidate.version,
        idempotency_key="candidate-create-new",
    )
    replay = await app.decide_candidate(
        retrospective.id,
        candidate.id,
        action="create_new",
        target_resource_id=None,
        action_payload={},
        expected_version=candidate.version,
        idempotency_key="candidate-create-new",
    )

    assert first.id == replay.id
    assert review.created == 1

    other_review = FakeReview(workspace_id="w2")
    connection2, app2, retrospective2, run2, _ = candidate_fixture(
        tmp_path / "other", review=other_review
    )
    candidate2 = next(
        item
        for item in app2.generate_candidates(retrospective2.id, run2.id)
        if item.candidate_kind == "review_question"
    )
    with pytest.raises(ValueError, match="工作区"):
        await app2.decide_candidate(
            retrospective2.id,
            candidate2.id,
            action="link_existing",
            target_resource_id="review-existing",
            action_payload={},
            expected_version=candidate2.version,
            idempotency_key="candidate-cross-workspace",
        )
    connection.close()
    connection2.close()


def test_action_decision_is_versioned_and_idempotent(tmp_path):
    connection, app, retrospective, run, _ = candidate_fixture(tmp_path)
    app.generate_candidates(retrospective.id, run.id)
    action = app.list_actions(retrospective.id)[0]

    completed = app.decide_action(
        retrospective.id,
        action.id,
        decision="completed",
        expected_version=action.version,
        idempotency_key="complete-action",
    )
    replay = app.decide_action(
        retrospective.id,
        action.id,
        decision="completed",
        expected_version=action.version,
        idempotency_key="complete-action",
    )

    assert completed.status == replay.status == "completed"
    assert completed.version == replay.version
    connection.close()


@pytest.mark.asyncio
async def test_batch_decision_preserves_success_when_one_adapter_fails(tmp_path):
    connection, retrospective_app, retrospective, run, _ = candidate_fixture(
        tmp_path, review=FailingReview()
    )
    candidates = retrospective_app.generate_candidates(retrospective.id, run.id)
    summary = next(item for item in candidates if item.candidate_kind == "summary")
    review = next(
        item for item in candidates if item.candidate_kind == "review_question"
    )
    root_application = SimpleNamespace(
        interview_retrospectives=lambda workspace_id: retrospective_app
    )
    api_app.dependency_overrides[get_agent_application] = lambda: root_application
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api_app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/interview-retrospectives/{retrospective.id}/candidates/batch-decision",
                json={
                    "workspaceId": "w1",
                    "decisions": [
                        {
                            "candidateId": summary.id,
                            "action": "include",
                            "expectedVersion": summary.version,
                            "idempotencyKey": "batch-summary-include",
                        },
                        {
                            "candidateId": review.id,
                            "action": "create_new",
                            "expectedVersion": review.version,
                            "idempotencyKey": "batch-review-create",
                        },
                    ],
                },
            )
    finally:
        api_app.dependency_overrides.pop(get_agent_application, None)

    assert response.status_code == 200, response.text
    assert [item["status"] for item in response.json()] == ["completed", "failed"]
    assert retrospective_app.repository.get_asset_candidate(summary.id).status == (
        "confirmed"
    )
    assert retrospective_app.repository.get_asset_candidate(review.id).status == (
        "failed"
    )
    connection.close()
