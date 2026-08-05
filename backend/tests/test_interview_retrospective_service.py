from __future__ import annotations

import pytest

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.interview_retrospectives.errors import (
    RetrospectiveBusy,
    RetrospectiveCleanupNotConfirmed,
    RetrospectiveSourceTooLarge,
    RetrospectiveSourceUnsupported,
    RetrospectiveTargetRequired,
    RetrospectiveNotFound,
)
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository
from app.interview_retrospectives.service import (
    InterviewRetrospectiveService,
    _document_anchor_segments,
)
from app.job_targets.repository import JobTargetRepository


def _service(tmp_path, *, workspace_id: str = "w1"):
    connection = connect_runtime_database(tmp_path)
    products = ProductRepository(connection)
    targets = JobTargetRepository(connection)
    service = InterviewRetrospectiveService(
        workspace_id=workspace_id,
        repository=InterviewRetrospectiveRepository(connection),
        job_targets=targets,
    )
    return connection, products, targets, service


def _sessions(products: ProductRepository, workspace_id: str = "w1"):
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
    return analysis, chat


def _retrospective(tmp_path):
    connection, products, targets, service = _service(tmp_path)
    target = targets.create_target(
        workspace_id="w1",
        role_name="高级后端工程师",
        seniority="5-8 年",
        company_name="示例公司",
        source_url=None,
    )
    analysis, chat = _sessions(products)
    retrospective = service.create(
        job_target_id=target.id,
        title="示例公司后端一面",
        round_label="一面",
        interview_date="2026-08-01",
        outcome="unrecorded",
        note="",
        analysis_session_id=analysis.id,
        chat_session_id=chat.id,
        idempotency_key="create-1",
    )
    return connection, service, retrospective


def test_create_rejects_target_from_another_workspace(tmp_path) -> None:
    connection, products, targets, service = _service(tmp_path)
    target = targets.create_target(
        workspace_id="w2",
        role_name="后端工程师",
        seniority="3-5 年",
        company_name=None,
        source_url=None,
    )
    analysis, chat = _sessions(products)

    with pytest.raises(RetrospectiveTargetRequired):
        service.create(
            job_target_id=target.id,
            title="错误归属",
            round_label="一面",
            interview_date=None,
            outcome="unrecorded",
            note="",
            analysis_session_id=analysis.id,
            chat_session_id=chat.id,
            idempotency_key="create-cross-workspace",
        )
    connection.close()


def test_create_and_source_import_are_idempotent(tmp_path) -> None:
    connection, service, retrospective = _retrospective(tmp_path)

    replayed = service.create(
        job_target_id=retrospective.job_target_id,
        title="示例公司后端一面",
        round_label="一面",
        interview_date="2026-08-01",
        outcome="unrecorded",
        note="",
        analysis_session_id=retrospective.analysis_session_id,
        chat_session_id=retrospective.chat_session_id,
        idempotency_key="create-1",
    )
    first = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="面试官：介绍一下项目\n我：主要负责服务治理。",
        file_name="interview.md",
        idempotency_key="source-1",
    )
    replayed_source = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="面试官：介绍一下项目\n我：主要负责服务治理。",
        file_name="interview.md",
        idempotency_key="source-1",
    )

    assert replayed.id == retrospective.id
    assert replayed_source.id == first.id
    assert first.ordinal == 1
    assert service.get(retrospective.id).active_source_version_id == first.id
    connection.close()


def test_source_import_rejects_more_than_500000_characters(tmp_path) -> None:
    connection, service, retrospective = _retrospective(tmp_path)

    with pytest.raises(RetrospectiveSourceTooLarge):
        service.add_source_version(
            retrospective.id,
            source_kind="transcript",
            body="字" * 500_001,
            file_name=None,
            idempotency_key="invalid-source",
        )
    connection.close()


def test_source_import_rejects_non_text_file_extension(tmp_path) -> None:
    connection, service, retrospective = _retrospective(tmp_path)

    with pytest.raises(RetrospectiveSourceUnsupported):
        service.add_source_version(
            retrospective.id,
            source_kind="transcript",
            body="有效文字",
            file_name="interview.docx",
            idempotency_key="invalid-file",
        )
    connection.close()


def test_cleanup_confirmation_requires_known_included_speakers(tmp_path) -> None:
    connection, service, retrospective = _retrospective(tmp_path)
    source = service.add_source_version(
        retrospective.id,
        source_kind="recollection",
        body="问了项目难点，我回答了缓存一致性。",
        file_name=None,
        idempotency_key="source-cleanup",
    )
    cleanup = service.create_cleanup_version(
        retrospective.id,
        source_version_id=source.id,
        input_digest="a" * 64,
        idempotency_key="cleanup-1",
    )
    cleanup = service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(
            {
                "speaker_role": "unknown",
                "raw_speaker_label": None,
                "display_name": "待确认",
                "body": "问了项目难点",
                "source_start": 0,
                "source_end": 7,
                "confidence": 0.4,
                "uncertainty_reason": "回忆记录没有说话人",
                "ignored": False,
            },
        ),
    )

    with pytest.raises(RetrospectiveCleanupNotConfirmed):
        service.confirm_cleanup(
            retrospective.id,
            cleanup.id,
            expected_version=cleanup.version,
            idempotency_key="confirm-cleanup",
        )
    connection.close()


def test_confirmed_document_anchor_plan_depends_only_on_the_final_document() -> None:
    document = (
        "面试官：介绍一下缓存治理。\n\n"
        "候选人：我参与了缓存一致性项目。\n\n"
        "这是一段没有可靠说话人标签的事后补充。"
    )

    first_plan = _document_anchor_segments(document)
    second_plan = _document_anchor_segments(document)

    assert first_plan == second_plan
    assert [item["speaker_role"] for item in first_plan] == [
        "interviewer",
        "candidate",
        "unknown",
    ]
    assert "".join(str(item["body"]) for item in first_plan) == document.replace(
        "\n\n", ""
    )


def test_clean_transcript_confirmation_requires_resolved_issues_and_valid_hash(
    tmp_path,
) -> None:
    connection, service, retrospective = _retrospective(tmp_path)
    source = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="我做过数字签明服务。",
        file_name=None,
        idempotency_key="source-document-confirm",
    )
    cleanup = service.create_cleanup_version(
        retrospective.id,
        source_version_id=source.id,
        input_digest="f" * 64,
        idempotency_key="cleanup-document-confirm",
    )
    cleanup = service.repository.replace_clean_transcript_document(
        cleanup.id,
        expected_version=cleanup.version,
        document_body="候选人：我做过数字签明服务。",
        review_issues=(
            {
                "document_start": 7,
                "document_end": 11,
                "excerpt": "数字签明",
                "suggestion": "数字签名",
                "issue_kind": "uncertain_term",
                "reason": "术语需要确认",
                "confidence": 0.7,
            },
        ),
    )

    with pytest.raises(RetrospectiveCleanupNotConfirmed, match="待核对"):
        service.confirm_cleanup(
            retrospective.id,
            cleanup.id,
            expected_version=cleanup.version,
            idempotency_key="confirm-pending-document",
        )

    issue = service.repository.list_transcript_review_issues(cleanup.id)[0]
    cleanup = service.update_clean_transcript_document(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        document_body="候选人：我做过数字签名服务。",
        review_issue_decisions=({"id": issue.id, "decision": "accepted"},),
    )
    connection.execute(
        "UPDATE interview_cleanup_versions SET document_sha256 = ? WHERE id = ?",
        ("0" * 64, cleanup.id),
    )
    connection.commit()
    with pytest.raises(RetrospectiveCleanupNotConfirmed, match="校验失败"):
        service.confirm_cleanup(
            retrospective.id,
            cleanup.id,
            expected_version=cleanup.version,
            idempotency_key="confirm-invalid-document-hash",
        )
    connection.close()


def test_clear_source_removes_recoverable_text_but_keeps_version_metadata(
    tmp_path,
) -> None:
    connection, service, retrospective = _retrospective(tmp_path)
    source = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="面试官：解释缓存一致性\n我：先介绍更新策略。",
        file_name="round-1.txt",
        idempotency_key="source-clear",
    )
    cleanup = service.create_cleanup_version(
        retrospective.id,
        source_version_id=source.id,
        input_digest="b" * 64,
        idempotency_key="cleanup-clear",
    )
    cleanup = service.repository.replace_clean_transcript_document(
        cleanup.id,
        expected_version=cleanup.version,
        document_body="面试官：解释缓存一致性\n\n候选人：先介绍更新策略。",
        review_issues=(
            {
                "document_start": 4,
                "document_end": 6,
                "excerpt": "解释",
                "suggestion": None,
                "issue_kind": "semantic",
                "reason": "需要确认",
                "confidence": 0.5,
            },
        ),
    )
    service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(
            {
                "speaker_role": "interviewer",
                "raw_speaker_label": "面试官",
                "display_name": "面试官 A",
                "body": "解释缓存一致性",
                "source_start": 0,
                "source_end": 9,
                "confidence": 1.0,
                "uncertainty_reason": None,
                "ignored": False,
            },
        ),
    )

    cleared = service.clear_source(
        retrospective.id,
        source.id,
        expected_version=service.get(retrospective.id).version,
        idempotency_key="clear-source",
    )

    assert cleared.body == ""
    assert cleared.cleared_at is not None
    assert len(cleared.content_sha256) == 64
    assert service.repository.list_segments(cleanup.id)[0].body == ""
    cleared_cleanup = service.repository.get_cleanup_version(cleanup.id)
    assert cleared_cleanup.document_body is None
    assert cleared_cleanup.document_sha256 is None
    assert service.repository.list_transcript_review_issues(cleanup.id) == ()
    connection.close()


def test_active_analysis_execution_blocks_recycle_and_permanent_delete(
    tmp_path,
) -> None:
    connection, products, _, service = _service(tmp_path)
    target = service.job_targets.create_target(
        workspace_id="w1",
        role_name="后端工程师",
        seniority="3-5 年",
        company_name=None,
        source_url=None,
    )
    analysis, chat = _sessions(products)
    retrospective = service.create(
        job_target_id=target.id,
        title="后端一面",
        round_label="一面",
        interview_date=None,
        outcome="pending",
        note="",
        analysis_session_id=analysis.id,
        chat_session_id=chat.id,
        idempotency_key="create-active",
    )
    products.create_execution(
        analysis.id,
        input={"retrospectiveId": retrospective.id},
        model_bindings={},
    )

    with pytest.raises(RetrospectiveBusy):
        service.recycle(
            retrospective.id,
            expected_version=retrospective.version,
            idempotency_key="recycle-active",
        )
    with pytest.raises(RetrospectiveBusy):
        service.delete_permanently(
            retrospective.id,
            expected_version=retrospective.version,
            idempotency_key="delete-active",
        )
    connection.close()


def test_lifecycle_round_trip_and_permanent_delete_remove_private_sessions(
    tmp_path,
) -> None:
    connection, service, retrospective = _retrospective(tmp_path)
    archived = service.archive(
        retrospective.id,
        expected_version=retrospective.version,
        idempotency_key="archive-1",
    )
    recycled = service.recycle(
        retrospective.id,
        expected_version=archived.version,
        idempotency_key="recycle-1",
    )
    restored = service.restore(
        retrospective.id,
        expected_version=recycled.version,
        idempotency_key="restore-1",
    )
    recycled_again = service.recycle(
        retrospective.id,
        expected_version=restored.version,
        idempotency_key="recycle-2",
    )

    service.delete_permanently(
        retrospective.id,
        expected_version=recycled_again.version,
        idempotency_key="delete-1",
    )

    with pytest.raises(RetrospectiveNotFound):
        service.repository.get_retrospective(retrospective.id)
    remaining_sessions = connection.execute(
        "SELECT COUNT(*) FROM agent_sessions WHERE id IN (?, ?)",
        (retrospective.analysis_session_id, retrospective.chat_session_id),
    ).fetchone()[0]
    assert remaining_sessions == 0
    connection.close()


def test_deletion_impact_separates_private_records_from_preserved_assets(
    tmp_path,
) -> None:
    connection, service, retrospective = _retrospective(tmp_path)
    service.add_source_version(
        retrospective.id,
        source_kind="recollection",
        body="回忆了一道系统设计题",
        file_name=None,
        idempotency_key="impact-source",
    )

    impact = service.deletion_impact(retrospective.id)

    assert impact["sourceVersions"] == 1
    assert impact["preservesReviewQuestions"] is True
    assert impact["preservesProfileAndProjects"] is True
    assert impact["preservesKnowledge"] is True
    connection.close()
