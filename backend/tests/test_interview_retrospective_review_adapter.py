from __future__ import annotations

from types import SimpleNamespace

from interview_retrospective_candidate_helpers import candidate_fixture


class FakeReview:
    workspace_id = "w1"

    def list_questions(self):
        return ()

    def get_confirmed_question(self, question_id: str):
        assert question_id == "review-confirmed"
        return SimpleNamespace(
            workspace_id="w1",
            snapshot=SimpleNamespace(question_id=question_id),
        )


def test_immediate_practice_requires_confirmed_existing_review_question(tmp_path):
    connection, app, retrospective, _run, _ = candidate_fixture(
        tmp_path, review=FakeReview()
    )

    link = app.immediate_practice_link(retrospective.id, "review-confirmed")

    assert link == (
        f"/review?questionId=review-confirmed&source=retrospective&id={retrospective.id}"
    )
    connection.close()
