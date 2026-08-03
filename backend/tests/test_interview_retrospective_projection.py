from __future__ import annotations

from app.interview_retrospectives.models import (
    CleanupVersionRecord,
    CleanupWorkItemRecord,
    SegmentRecord,
    SourceVersionRecord,
    TranscriptCorrectionRecord,
    TranscriptReviewIssueRecord,
)
from app.interview_retrospectives.projection import (
    cleanup_version_resource,
    source_version_resource,
)


def test_source_projection_returns_body_only_for_explicit_detail() -> None:
    source = SourceVersionRecord(
        id="source-1",
        retrospective_id="retro-1",
        ordinal=1,
        source_kind="transcript",
        recording_coverage="mixed_unknown",
        file_name="round.md",
        body="private interview transcript",
        content_sha256="a" * 64,
        cleared_at=None,
        created_at="2026-08-01T00:00:00Z",
    )

    summary = source_version_resource(source, include_body=False)
    detail = source_version_resource(source, include_body=True)

    assert "body" not in summary
    assert summary["bodyAvailable"] is True
    assert detail["body"] == "private interview transcript"


def test_cleared_source_detail_never_returns_an_empty_body_as_available() -> None:
    source = SourceVersionRecord(
        id="source-1",
        retrospective_id="retro-1",
        ordinal=1,
        source_kind="transcript",
        recording_coverage="mixed_unknown",
        file_name=None,
        body="",
        content_sha256="a" * 64,
        cleared_at="2026-08-02T00:00:00Z",
        created_at="2026-08-01T00:00:00Z",
    )

    detail = source_version_resource(source, include_body=True)

    assert detail["bodyAvailable"] is False
    assert detail["body"] is None


def test_cleanup_projection_exposes_corrections_and_persisted_progress_times() -> None:
    cleanup = CleanupVersionRecord(
        id="cleanup-1",
        retrospective_id="retro-1",
        source_version_id="source-1",
        ordinal=1,
        execution_id="run-1",
        input_digest="a" * 64,
        status="running",
        stage="cleaning",
        control_intent=None,
        confirmed_at=None,
        version=2,
        created_at="2026-08-02 00:00:00",
        updated_at="2026-08-02 00:01:10",
    )
    segment = SegmentRecord(
        id="segment-1",
        cleanup_version_id=cleanup.id,
        ordinal=1,
        speaker_role="candidate",
        raw_speaker_label="我",
        display_name="候选人",
        body="我使用 Redis",
        source_start=0,
        source_end=7,
        confidence=0.96,
        uncertainty_reason=None,
        ignored=False,
        version=1,
        created_at="2026-08-02 00:00:30",
        updated_at="2026-08-02 00:00:30",
    )
    correction = TranscriptCorrectionRecord(
        id="correction-1",
        cleanup_version_id=cleanup.id,
        segment_id=segment.id,
        source_start=4,
        source_end=7,
        original_text="瑞迪斯",
        original_sha256="b" * 64,
        suggested_text="Redis",
        adopted_text="Redis",
        change_type="recognition",
        risk_level="low",
        reason="技术名词可唯一确定",
        confidence=0.96,
        decision="auto_accepted",
        created_at="2026-08-02 00:00:30",
        updated_at="2026-08-02 00:00:30",
    )
    work_item = CleanupWorkItemRecord(
        id="item-1",
        cleanup_version_id=cleanup.id,
        work_key="window:0:4000",
        source_start=0,
        source_end=4_000,
        input_digest="c" * 64,
        status="running",
        output=None,
        attempt_count=1,
        last_error_code=None,
        created_at="2026-08-02 00:00:10",
        updated_at="2026-08-02 00:00:30",
    )

    resource = cleanup_version_resource(
        cleanup,
        segments=(segment,),
        corrections=(correction,),
        work_items=(work_item,),
    )

    assert resource["activeSince"] == "2026-08-02 00:00:30"
    assert resource["latestProgressAt"] == "2026-08-02 00:00:30"
    assert resource["corrections"] == [
        {
            "id": "correction-1",
            "segmentId": "segment-1",
            "sourceStart": 4,
            "sourceEnd": 7,
            "originalText": "瑞迪斯",
            "suggestedText": "Redis",
            "adoptedText": "Redis",
            "changeType": "recognition",
            "riskLevel": "low",
            "reason": "技术名词可唯一确定",
            "confidence": 0.96,
            "decision": "auto_accepted",
        }
    ]


def test_cleanup_projection_exposes_the_single_document_and_sparse_issues() -> None:
    cleanup = CleanupVersionRecord(
        id="cleanup-1",
        retrospective_id="retro-1",
        source_version_id="source-1",
        ordinal=1,
        execution_id="run-1",
        input_digest="a" * 64,
        status="review_pending",
        stage="waiting_for_review",
        control_intent=None,
        confirmed_at=None,
        version=3,
        created_at="2026-08-02 00:00:00",
        updated_at="2026-08-02 00:01:10",
        document_body="候选人：我做过数字签名服务。",
        document_sha256=(
            "588258e59acd5d596d49977ca2b035f6c3f94172d67d6a374f50ffa58f00a2dc"
        ),
    )
    issue = TranscriptReviewIssueRecord(
        id="issue-1",
        cleanup_version_id=cleanup.id,
        ordinal=1,
        document_start=7,
        document_end=11,
        excerpt="数字签名",
        suggestion=None,
        issue_kind="uncertain_term",
        reason="需要确认业务术语",
        confidence=0.7,
        decision="pending",
        created_at="2026-08-02 00:01:00",
        updated_at="2026-08-02 00:01:00",
    )

    resource = cleanup_version_resource(
        cleanup,
        segments=(),
        review_issues=(issue,),
    )

    assert resource["documentBody"] == "候选人：我做过数字签名服务。"
    assert resource["documentSha256"] == cleanup.document_sha256
    assert resource["reviewIssues"] == [
        {
            "id": "issue-1",
            "ordinal": 1,
            "documentStart": 7,
            "documentEnd": 11,
            "excerpt": "数字签名",
            "suggestion": None,
            "issueKind": "uncertain_term",
            "reason": "需要确认业务术语",
            "confidence": 0.7,
            "decision": "pending",
        }
    ]
