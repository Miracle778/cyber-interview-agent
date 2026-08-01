from __future__ import annotations

from app.interview_retrospectives.models import (
    RetrospectiveRecord,
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
