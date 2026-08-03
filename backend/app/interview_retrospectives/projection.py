from __future__ import annotations

import json

from app.graphs.interview_retrospective_cleanup import reduce_cleanup_segments
from app.interview_retrospectives.models import (
    ActionItemRecord,
    AnalysisRunRecord,
    AnalysisWorkItemRecord,
    AssetCandidateRecord,
    CleanupVersionRecord,
    CleanupWorkItemRecord,
    GapRecord,
    QuestionAnalysisRecord,
    QuestionUnitRecord,
    RetrospectiveRecord,
    SegmentRecord,
    SourceVersionRecord,
    TranscriptCorrectionRecord,
    TranscriptReviewIssueRecord,
)


def retrospective_resource(
    record: RetrospectiveRecord, *, active_source_available: bool
) -> dict[str, object]:
    return {
        "id": record.id,
        "workspaceId": record.workspace_id,
        "jobTargetId": record.job_target_id,
        "title": record.title,
        "roundLabel": record.round_label,
        "interviewDate": record.interview_date,
        "outcome": record.outcome,
        "note": record.note,
        "lifecycleStatus": record.lifecycle_status,
        "activeSourceVersionId": record.active_source_version_id,
        "activeSourceAvailable": active_source_available,
        "activeCleanupVersionId": record.active_cleanup_version_id,
        "activeAnalysisRunId": record.active_analysis_run_id,
        "version": record.version,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
    }


def source_version_resource(
    record: SourceVersionRecord, *, include_body: bool
) -> dict[str, object]:
    available = record.cleared_at is None
    resource: dict[str, object] = {
        "id": record.id,
        "retrospectiveId": record.retrospective_id,
        "ordinal": record.ordinal,
        "sourceKind": record.source_kind,
        "recordingCoverage": record.recording_coverage,
        "fileName": record.file_name,
        "contentSha256": record.content_sha256,
        "bodyAvailable": available,
        "clearedAt": record.cleared_at,
        "createdAt": record.created_at,
    }
    if include_body:
        resource["body"] = record.body if available else None
    return resource


def segment_resource(record: SegmentRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "ordinal": record.ordinal,
        "speakerRole": record.speaker_role,
        "rawSpeakerLabel": record.raw_speaker_label,
        "displayName": record.display_name,
        "body": record.body,
        "sourceStart": record.source_start,
        "sourceEnd": record.source_end,
        "confidence": record.confidence,
        "uncertaintyReason": record.uncertainty_reason,
        "ignored": record.ignored,
        "version": record.version,
    }


def correction_resource(record: TranscriptCorrectionRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "segmentId": record.segment_id,
        "sourceStart": record.source_start,
        "sourceEnd": record.source_end,
        "originalText": record.original_text,
        "suggestedText": record.suggested_text,
        "adoptedText": record.adopted_text,
        "changeType": record.change_type,
        "riskLevel": record.risk_level,
        "reason": record.reason,
        "confidence": record.confidence,
        "decision": record.decision,
    }


def transcript_review_issue_resource(
    record: TranscriptReviewIssueRecord,
) -> dict[str, object]:
    return {
        "id": record.id,
        "ordinal": record.ordinal,
        "documentStart": record.document_start,
        "documentEnd": record.document_end,
        "excerpt": record.excerpt,
        "suggestion": record.suggestion,
        "issueKind": record.issue_kind,
        "reason": record.reason,
        "confidence": record.confidence,
        "decision": record.decision,
    }


def cleanup_version_resource(
    record: CleanupVersionRecord,
    *,
    segments: tuple[SegmentRecord, ...],
    corrections: tuple[TranscriptCorrectionRecord, ...] = (),
    review_issues: tuple[TranscriptReviewIssueRecord, ...] = (),
    work_items: tuple[CleanupWorkItemRecord, ...] = (),
) -> dict[str, object]:
    completed_items = sum(item.status == "completed" for item in work_items)
    active_items = sum(item.status == "running" for item in work_items)
    failed_items = sum(item.status == "retryable" for item in work_items)
    current_item = next(
        (
            item
            for item in work_items
            if item.status in {"running", "retryable", "interrupted", "pending"}
        ),
        None,
    )
    failed_item = next(
        (item for item in work_items if item.last_error_code is not None),
        None,
    )
    running_items = tuple(item for item in work_items if item.status == "running")
    active_since = min(
        (item.updated_at for item in running_items),
        default=None,
    )
    latest_progress_at = max(
        (item.updated_at for item in work_items),
        default=None,
    )
    segment_items = [segment_resource(item) for item in segments]
    if not segment_items:
        completed_outputs = [
            item.output.get("segments", [])
            for item in work_items
            if item.status == "completed" and item.output is not None
        ]
        segment_items = [
            _preview_segment_resource(record.id, item)
            for item in reduce_cleanup_segments(completed_outputs)
        ]
    return {
        "id": record.id,
        "retrospectiveId": record.retrospective_id,
        "sourceVersionId": record.source_version_id,
        "ordinal": record.ordinal,
        "executionId": record.execution_id,
        "status": record.status,
        "stage": record.stage,
        "controlIntent": record.control_intent,
        "confirmedAt": record.confirmed_at,
        "documentBody": record.document_body,
        "documentSha256": record.document_sha256,
        "completedItems": completed_items,
        "totalItems": len(work_items),
        "activeItems": active_items,
        "failedItems": failed_items,
        "currentWorkKey": None if current_item is None else current_item.work_key,
        "lastErrorCode": (
            None if failed_item is None else failed_item.last_error_code
        ),
        "activeSince": active_since,
        "latestProgressAt": latest_progress_at,
        "version": record.version,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
        "segments": segment_items,
        "corrections": [correction_resource(item) for item in corrections],
        "reviewIssues": [
            transcript_review_issue_resource(item) for item in review_issues
        ],
    }


def _preview_segment_resource(
    cleanup_id: str, item: dict[str, object]
) -> dict[str, object]:
    ordinal = int(item["ordinal"])
    return {
        "id": f"{cleanup_id}:preview:{ordinal}",
        "ordinal": ordinal,
        "speakerRole": item["speakerRole"],
        "rawSpeakerLabel": item.get("rawSpeakerLabel"),
        "displayName": item["displayName"],
        "body": item["text"],
        "sourceStart": item["sourceStart"],
        "sourceEnd": item["sourceEnd"],
        "confidence": item["confidence"],
        "uncertaintyReason": item.get("uncertaintyReason"),
        "ignored": False,
        "version": 1,
    }


def question_resource(record: QuestionUnitRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "retrospectiveId": record.retrospective_id,
        "cleanupVersionId": record.cleanup_version_id,
        "ordinal": record.ordinal,
        "questionKind": record.question_kind,
        "origin": record.origin,
        "questionText": record.question_text,
        "questionSegmentIds": list(record.question_segment_ids),
        "answerSegmentIds": list(record.answer_segment_ids),
        "inferenceBasis": record.inference_basis,
        "confidence": record.confidence,
        "decisionStatus": record.decision_status,
        "version": record.version,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
    }


def analysis_run_resource(record: AnalysisRunRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "retrospectiveId": record.retrospective_id,
        "cleanupVersionId": record.cleanup_version_id,
        "executionId": record.execution_id,
        "retryOfAnalysisRunId": record.retry_of_analysis_run_id,
        "status": record.status,
        "stage": record.stage,
        "controlIntent": record.control_intent,
        "completedItems": record.completed_items,
        "totalItems": record.total_items,
        "currentWorkKey": record.current_work_key,
        "cumulativeElapsedMs": record.cumulative_elapsed_ms,
        "latestProgressAt": record.latest_progress_at,
        "summary": (
            None if record.summary_json is None else json.loads(record.summary_json)
        ),
        "version": record.version,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
    }


def question_analysis_resource(
    record: QuestionAnalysisRecord,
    gaps: tuple[GapRecord, ...] = (),
) -> dict[str, object]:
    return {
        "id": record.id,
        "analysisRunId": record.analysis_run_id,
        "questionUnitId": record.question_unit_id,
        "verdict": record.verdict,
        "strengths": list(record.strengths),
        "improvements": list(record.improvements),
        "omissions": list(record.omissions),
        "gaps": [
            {
                "kind": gap.gap_kind,
                "summary": gap.summary,
                "evidenceSegmentIds": list(gap.evidence),
            }
            for gap in gaps
        ],
        "evidenceLevel": record.evidence_level,
        "confidence": record.confidence,
        "improvementOutline": list(record.improvement_outline),
        "suggestedAnswer": record.suggested_answer,
        "sourceExcerpt": record.source_excerpt if record.source_available else "",
        "sourceAvailable": record.source_available,
        "resultStatus": record.result_status,
        "version": record.version,
    }


def analysis_work_item_resource(
    record: AnalysisWorkItemRecord,
) -> dict[str, object]:
    return {
        "id": record.id,
        "questionUnitId": record.question_unit_id,
        "workKey": record.work_key,
        "status": record.status,
        "attemptCount": record.attempt_count,
        "lastErrorCode": record.last_error_code,
        "updatedAt": record.updated_at,
    }


def asset_candidate_resource(record: AssetCandidateRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "retrospectiveId": record.retrospective_id,
        "analysisRunId": record.analysis_run_id,
        "questionUnitId": record.question_unit_id,
        "candidateKind": record.candidate_kind,
        "fingerprint": record.fingerprint,
        "payload": json.loads(record.payload_json),
        "matches": json.loads(record.match_json),
        "status": record.status,
        "targetResourceType": record.target_resource_type,
        "targetResourceId": record.target_resource_id,
        "lastErrorCode": record.last_error_code,
        "version": record.version,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
    }


def action_item_resource(record: ActionItemRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "retrospectiveId": record.retrospective_id,
        "analysisRunId": record.analysis_run_id,
        "questionUnitId": record.question_unit_id,
        "gapId": record.gap_id,
        "actionKind": record.action_kind,
        "title": record.title,
        "detail": record.detail,
        "status": record.status,
        "version": record.version,
        "completedAt": record.completed_at,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
    }
