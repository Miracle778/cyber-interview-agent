from __future__ import annotations

from app.interview_retrospectives.models import (
    CleanupVersionRecord,
    RetrospectiveRecord,
    SegmentRecord,
    SourceVersionRecord,
)


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
