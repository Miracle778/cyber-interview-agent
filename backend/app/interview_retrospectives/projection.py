from __future__ import annotations

from app.interview_retrospectives.models import (
    AnalysisRunRecord,
    AnalysisWorkItemRecord,
    CleanupVersionRecord,
    QuestionAnalysisRecord,
    QuestionUnitRecord,
    RetrospectiveRecord,
    SegmentRecord,
    SourceVersionRecord,
)
import json


def retrospective_resource(record: RetrospectiveRecord) -> dict[str, object]:
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


def cleanup_version_resource(
    record: CleanupVersionRecord,
    *,
    segments: tuple[SegmentRecord, ...],
) -> dict[str, object]:
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
        "version": record.version,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
        "segments": [segment_resource(item) for item in segments],
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
) -> dict[str, object]:
    return {
        "id": record.id,
        "analysisRunId": record.analysis_run_id,
        "questionUnitId": record.question_unit_id,
        "verdict": record.verdict,
        "strengths": list(record.strengths),
        "improvements": list(record.improvements),
        "omissions": list(record.omissions),
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
