import hashlib

from interview_retrospective_candidate_helpers import candidate_fixture


def test_question_correction_creates_local_run_and_preserves_other_analysis(
    tmp_path,
) -> None:
    connection, application, retrospective, source_run, questions = candidate_fixture(
        tmp_path
    )
    repository = application.repository
    repository.mark_analysis_completed(source_run.id, summary={"questionCount": 2})
    changed = questions[0]
    untouched = questions[1]

    updated = repository.apply_question_correction(
        changed.id,
        expected_version=changed.version,
        question_text="如何保证缓存与数据库最终一致？",
    )
    new_run = repository.insert_local_reanalysis_run(
        retrospective.id,
        source_run_id=source_run.id,
        question_id=changed.id,
        input_digest=hashlib.sha256(b"local-correction").hexdigest(),
        context_snapshot={"correctionType": "question_text_correction"},
    )

    assert updated.question_text == "如何保证缓存与数据库最终一致？"
    assert updated.version == changed.version + 1
    assert new_run.retry_of_analysis_run_id == source_run.id
    assert [
        item.work_key for item in repository.list_analysis_work_items(new_run.id)
    ] == [
        f"question_analysis:{changed.id}",
        "gap_verification",
        "candidate_generation",
        "final_projection",
    ]
    assert (
        repository.get_question_analysis(new_run.id, untouched.id).suggested_answer
        == repository.get_question_analysis(
            source_run.id, untouched.id
        ).suggested_answer
    )
    connection.close()


def test_rejected_correction_does_not_change_question_or_create_run(tmp_path) -> None:
    connection, application, retrospective, source_run, questions = candidate_fixture(
        tmp_path
    )
    repository = application.repository
    question = questions[0]
    proposal = repository.create_correction_proposal(
        retrospective.id,
        chat_message_id=None,
        proposal_type="question_text_correction",
        target_question_id=question.id,
        source_cleanup_version_id=question.cleanup_version_id,
        source_analysis_run_id=source_run.id,
        before={"questionText": question.question_text},
        after={"questionText": "另一个问题"},
        rationale="用户指出转写有误",
        expected_version=question.version,
    )

    rejected = repository.decide_correction_proposal(proposal.id, status="rejected")

    assert rejected.status == "rejected"
    assert repository.get_question(question.id).question_text == question.question_text
    assert repository.current_analysis_run(retrospective.id).id == source_run.id
    connection.close()
