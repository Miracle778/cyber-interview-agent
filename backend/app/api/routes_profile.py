from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile, status

from app.api.dependencies import get_agent_application
from app.application.session_service import SessionBusyError
from app.application.workspace_runtime import AgentApplication
from app.schemas.agent import SessionResource
from app.profile.errors import ProfileDeletionPlanConflict, ProfileIngestBusy
from app.profile.models import (
    ClaimDecisionResult,
    ClaimProposalRecord,
    ClaimReviewDetail,
    DecideProposalCommand,
    EvidenceRecord,
    ProfileClaimVersionRecord,
    ProfileActionPlanRecord,
    ProfileMaterialRecord,
    ProfileMaterialVersionRecord,
)
from app.profile.service import MaterialUploadResult, ProfileService
from app.profile.storage import MAX_MATERIAL_BYTES
from app.schemas.profile import (
    AcceptedMaterialRetryResource,
    AcceptedMaterialUploadResource,
    AffectedClaimResource,
    BatchClaimDecisionCommand,
    BatchClaimDecisionItemResource,
    BatchClaimDecisionResource,
    ClaimConflictResource,
    ClaimDecisionCommand,
    ClaimDecisionResource,
    ClaimProposalResource,
    ClaimReviewResource,
    ClaimReviewWorkspaceResource,
    ClaimVersionResource,
    ConfirmedProfileContextCommand,
    ConfirmedProfileContextItemResource,
    ConfirmedProfileContextResource,
    DeletionItemReceiptResource,
    EvidencePageResource,
    MaterialActionCommand,
    MaterialDeletionPreviewCommand,
    MaterialDeletionPreviewResource,
    MaterialProcessingStageResource,
    PermanentMaterialDeletionCommand,
    PermanentMaterialDeletionResource,
    ProfileEvidenceResource,
    ProfileExecutionSummaryResource,
    ProfileMaterialResource,
    ProfileMaterialVersionDetailResource,
    ProfileMaterialVersionResource,
    CreateProfileSessionCommand,
    ProfileActionPlanCommand,
    ProfileActionPlanItemResource,
    ProfileActionPlanResource,
    ProfileActionPlanRetryCommand,
    ProfileAssessmentResource,
    ProposalCountsResource,
    RetryMaterialVersionCommand,
    SetPrimaryMaterialCommand,
)


router = APIRouter(tags=["profile"])


@router.post(
    "/api/workspaces/{workspace_id}/profile/sessions",
    response_model=SessionResource,
    status_code=status.HTTP_201_CREATED,
)
async def create_profile_session(
    workspace_id: str,
    command: CreateProfileSessionCommand,
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.create_profile_session(
        workspace_id=workspace_id,
        title=None if command.title is None else command.title.strip() or None,
    )


@router.get(
    "/api/workspaces/{workspace_id}/profile/sessions",
    response_model=list[SessionResource],
)
def list_profile_sessions(
    workspace_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    return application.list_profile_sessions(workspace_id)


@router.get(
    "/api/profile/assessments/{assessment_id}",
    response_model=ProfileAssessmentResource,
)
def get_profile_assessment(
    assessment_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
) -> ProfileAssessmentResource:
    service = application.profile(workspace_id)
    assessment = service.get_assessment(assessment_id)
    proposal_ids = [
        row[0]
        for row in service.connection.execute(
            "SELECT id FROM profile_claim_proposals "
            "WHERE created_by_execution_id = ? ORDER BY created_at, id",
            (assessment.created_by_execution_id,),
        ).fetchall()
    ] if assessment.created_by_execution_id is not None else []
    return ProfileAssessmentResource(
        id=assessment.id,
        workspace_id=assessment.workspace_id,
        base_profile_version=assessment.base_profile_version,
        current_profile_version=service.repository.profile_snapshot(
            workspace_id
        ).profile_version,
        result=assessment.result,
        proposal_ids=proposal_ids,
        created_by_execution_id=assessment.created_by_execution_id,
        created_at=assessment.created_at,
    )


@router.get(
    "/api/profile/action-plans/{plan_id}",
    response_model=ProfileActionPlanResource,
)
def get_profile_action_plan(
    plan_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
) -> ProfileActionPlanResource:
    service = application.profile(workspace_id)
    return _action_plan_resource(service, service.get_action_plan(plan_id))


@router.post(
    "/api/profile/action-plans/{plan_id}/confirm",
    response_model=ProfileActionPlanResource,
)
def confirm_profile_action_plan(
    plan_id: str,
    command: ProfileActionPlanCommand,
    application: AgentApplication = Depends(get_agent_application),
) -> ProfileActionPlanResource:
    service = application.profile(command.workspace_id)
    return _action_plan_resource(
        service,
        service.confirm_action_plan(
            plan_id, expected_version=command.expected_version
        ),
    )


@router.post(
    "/api/profile/action-plans/{plan_id}/cancel",
    response_model=ProfileActionPlanResource,
)
def cancel_profile_action_plan(
    plan_id: str,
    command: ProfileActionPlanCommand,
    application: AgentApplication = Depends(get_agent_application),
) -> ProfileActionPlanResource:
    service = application.profile(command.workspace_id)
    return _action_plan_resource(
        service,
        service.cancel_action_plan(
            plan_id, expected_version=command.expected_version
        ),
    )


@router.post(
    "/api/profile/action-plans/{plan_id}/retry",
    response_model=ProfileActionPlanResource,
)
def retry_profile_action_plan(
    plan_id: str,
    command: ProfileActionPlanRetryCommand,
    application: AgentApplication = Depends(get_agent_application),
) -> ProfileActionPlanResource:
    service = application.profile(command.workspace_id)
    return _action_plan_resource(service, service.retry_action_plan(plan_id))


@router.post(
    "/api/workspaces/{workspace_id}/profile/materials",
    response_model=AcceptedMaterialUploadResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_profile_material(
    workspace_id: str,
    title: Annotated[str, Form(min_length=1, max_length=200)],
    primary_role: Annotated[str, Form(alias="primaryRole", min_length=1, max_length=80)],
    file: Annotated[UploadFile, File(...)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    application: AgentApplication = Depends(get_agent_application),
) -> AcceptedMaterialUploadResource:
    content = await file.read(MAX_MATERIAL_BYTES + 1)
    result = application.profile(workspace_id).upload_material(
        file_name=file.filename or "",
        content=content,
        title=title.strip(),
        primary_role=primary_role.strip(),
        idempotency_key=idempotency_key,
    )
    return _accepted_upload(result)


@router.get(
    "/api/workspaces/{workspace_id}/profile/materials",
    response_model=list[ProfileMaterialResource],
)
def list_profile_materials(
    workspace_id: str,
    include_archived: Annotated[bool, Query(alias="includeArchived")] = False,
    application: AgentApplication = Depends(get_agent_application),
) -> list[ProfileMaterialResource]:
    service = application.profile(workspace_id)
    return [
        _material_resource(service, item)
        for item in service.list_materials(include_archived=include_archived)
    ]


@router.post(
    "/api/profile/materials/{material_id}/versions",
    response_model=AcceptedMaterialUploadResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def add_profile_material_version(
    material_id: str,
    workspace_id: Annotated[str, Form(alias="workspaceId")],
    file: Annotated[UploadFile, File(...)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    application: AgentApplication = Depends(get_agent_application),
) -> AcceptedMaterialUploadResource:
    content = await file.read(MAX_MATERIAL_BYTES + 1)
    result = application.profile(workspace_id).add_material_version(
        material_id=material_id,
        file_name=file.filename or "",
        content=content,
        idempotency_key=idempotency_key,
    )
    return _accepted_upload(result)


@router.get(
    "/api/profile/materials/{material_id}/versions",
    response_model=list[ProfileMaterialVersionResource],
)
def list_profile_material_versions(
    material_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
) -> list[ProfileMaterialVersionResource]:
    service = application.profile(workspace_id)
    return [
        _version_resource(service, item)
        for item in service.list_material_versions(material_id)
    ]


@router.get(
    "/api/profile/material-versions/{version_id}",
    response_model=ProfileMaterialVersionDetailResource,
)
def get_profile_material_version(
    version_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    evidence_offset: Annotated[int, Query(alias="evidenceOffset", ge=0)] = 0,
    evidence_limit: Annotated[int, Query(alias="evidenceLimit", ge=1, le=100)] = 50,
    application: AgentApplication = Depends(get_agent_application),
) -> ProfileMaterialVersionDetailResource:
    service = application.profile(workspace_id)
    version = service.get_material_version(version_id)
    material = service.get_material(version.material_id)
    evidence = service.repository.list_evidence_for_version(version.id)
    page = evidence[evidence_offset : evidence_offset + evidence_limit]
    counts = service.repository.proposal_counts_for_version(version.id)
    execution = service.latest_execution(version.id)
    return ProfileMaterialVersionDetailResource(
        **_version_resource(service, version).model_dump(),
        material=_material_resource(service, material),
        evidence_page=EvidencePageResource(
            items=[_evidence_resource(item) for item in page],
            offset=evidence_offset,
            limit=evidence_limit,
            total=len(evidence),
            has_more=evidence_offset + len(page) < len(evidence),
        ),
        proposal_counts=ProposalCountsResource(**counts),
        execution=(
            None
            if execution is None
            else ProfileExecutionSummaryResource(
                id=execution.id,
                status=execution.status,
                error_code=execution.error_code,
                created_at=execution.created_at,
                started_at=execution.started_at,
                finished_at=execution.finished_at,
                retryable=execution.status in {"failed", "interrupted", "cancelled"},
            )
        ),
    )


@router.post(
    "/api/profile/material-versions/{version_id}/retry",
    response_model=AcceptedMaterialRetryResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_profile_material_version(
    version_id: str,
    command: RetryMaterialVersionCommand,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    application: AgentApplication = Depends(get_agent_application),
) -> AcceptedMaterialRetryResource:
    service = application.profile(command.workspace_id)
    try:
        execution = service.retry_version_ingest(
            version_id, idempotency_key=idempotency_key
        )
    except SessionBusyError as error:
        raise ProfileIngestBusy("profile ingest execution is still active") from error
    version = service.get_material_version(version_id)
    return AcceptedMaterialRetryResource(
        version_id=version.id,
        execution_id=execution.id,
        processing_status=version.processing_status,
    )


@router.post(
    "/api/profile/materials/{material_id}/archive",
    response_model=ProfileMaterialResource,
)
def archive_profile_material(
    material_id: str,
    command: MaterialActionCommand,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    application: AgentApplication = Depends(get_agent_application),
) -> ProfileMaterialResource:
    service = application.profile(command.workspace_id)
    result = service.archive_material(
        material_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    return _material_resource(service, result)


@router.post(
    "/api/profile/materials/{material_id}/restore",
    response_model=ProfileMaterialResource,
)
def restore_profile_material(
    material_id: str,
    command: MaterialActionCommand,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    application: AgentApplication = Depends(get_agent_application),
) -> ProfileMaterialResource:
    service = application.profile(command.workspace_id)
    result = service.restore_material(
        material_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    return _material_resource(service, result)


@router.post(
    "/api/profile/materials/{material_id}/primary",
    response_model=ProfileMaterialResource,
)
def set_primary_profile_material_version(
    material_id: str,
    command: SetPrimaryMaterialCommand,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    application: AgentApplication = Depends(get_agent_application),
) -> ProfileMaterialResource:
    service = application.profile(command.workspace_id)
    result = service.set_primary_version(
        material_id,
        command.version_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    return _material_resource(service, result)


@router.get(
    "/api/workspaces/{workspace_id}/profile/claims",
    response_model=ClaimReviewWorkspaceResource,
)
def list_profile_claims(
    workspace_id: str,
    application: AgentApplication = Depends(get_agent_application),
) -> ClaimReviewWorkspaceResource:
    service = application.profile(workspace_id)
    snapshot = service.claim_review_snapshot()
    return ClaimReviewWorkspaceResource(
        workspace_id=workspace_id,
        profile_version=snapshot.profile_version,
        claims=[_claim_review_resource(service, item) for item in snapshot.claims],
        proposals=[_proposal_resource(service, item) for item in snapshot.proposals],
    )


@router.post(
    "/api/workspaces/{workspace_id}/profile/confirmed-context",
    response_model=ConfirmedProfileContextResource,
)
def get_confirmed_profile_context(
    workspace_id: str,
    command: ConfirmedProfileContextCommand,
    application: AgentApplication = Depends(get_agent_application),
) -> ConfirmedProfileContextResource:
    context = application.profile(workspace_id).confirmed_profile_context(
        purpose=command.purpose,
        claim_types=tuple(command.claim_types),
        claim_ids=tuple(command.claim_ids),
        sensitive_data_policy=command.sensitive_data_policy,
        limit=command.limit,
    )
    return ConfirmedProfileContextResource(
        workspace_id=context.workspace_id,
        purpose=context.purpose,
        profile_version=context.profile_version,
        items=[
            ConfirmedProfileContextItemResource(
                claim_id=item.claim_id,
                claim_version_id=item.claim_version_id,
                claim_type=item.claim_type,
                value=item.value,
                support_status=item.support_status,
                evidence_ids=list(item.evidence_ids),
            )
            for item in context.items
        ],
    )


@router.get(
    "/api/profile/claims/{claim_id}", response_model=ClaimReviewResource
)
def get_profile_claim(
    claim_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
) -> ClaimReviewResource:
    service = application.profile(workspace_id)
    return _claim_review_resource(service, service.get_claim_review(claim_id))


@router.get(
    "/api/profile/claims/{claim_id}/versions",
    response_model=list[ClaimVersionResource],
)
def list_profile_claim_versions(
    claim_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
) -> list[ClaimVersionResource]:
    detail = application.profile(workspace_id).get_claim_review(claim_id)
    return [_claim_version_resource(item) for item in detail.versions]


@router.post(
    "/api/profile/claim-proposals/{proposal_id}/accept",
    response_model=ClaimDecisionResource,
)
def accept_profile_claim_proposal(
    proposal_id: str,
    command: ClaimDecisionCommand,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    application: AgentApplication = Depends(get_agent_application),
) -> ClaimDecisionResource:
    result = application.profile(command.workspace_id).decide_claim_proposal(
        proposal_id,
        decision="accepted",
        expected_version=command.expected_version,
        edited_value=command.edited_value,
        idempotency_key=idempotency_key,
    )
    return _decision_resource(result)


@router.post(
    "/api/profile/claim-proposals/{proposal_id}/reject",
    response_model=ClaimDecisionResource,
)
def reject_profile_claim_proposal(
    proposal_id: str,
    command: ClaimDecisionCommand,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    application: AgentApplication = Depends(get_agent_application),
) -> ClaimDecisionResource:
    result = application.profile(command.workspace_id).decide_claim_proposal(
        proposal_id,
        decision="rejected",
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    return _decision_resource(result)


@router.post(
    "/api/profile/claim-proposals/batch-decide",
    response_model=BatchClaimDecisionResource,
)
def batch_decide_profile_claim_proposals(
    command: BatchClaimDecisionCommand,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    application: AgentApplication = Depends(get_agent_application),
) -> BatchClaimDecisionResource:
    result = application.profile(command.workspace_id).batch_decide_claim_proposals(
        tuple(
            DecideProposalCommand(
                proposal_id=item.proposal_id,
                decision=item.decision,
                expected_status="pending",
                expected_claim_version=item.expected_version,
                edited_value=item.edited_value,
                idempotency_key=f"{idempotency_key}:{item.proposal_id}",
            )
            for item in command.decisions
        )
    )
    completed = {item.proposal_id: item for item in result.completed}
    items: list[BatchClaimDecisionItemResource] = []
    for command_item in command.decisions:
        if command_item.proposal_id in completed:
            items.append(
                BatchClaimDecisionItemResource(
                    proposal_id=command_item.proposal_id,
                    status="completed",
                    result=_decision_resource(completed[command_item.proposal_id]),
                    retryable=False,
                )
            )
        elif command_item.proposal_id in result.conflicts:
            items.append(
                BatchClaimDecisionItemResource(
                    proposal_id=command_item.proposal_id,
                    status="conflict",
                    error_code="profile_claim_version_conflict",
                    retryable=True,
                )
            )
        else:
            items.append(
                BatchClaimDecisionItemResource(
                    proposal_id=command_item.proposal_id,
                    status="failed_terminal",
                    error_code="profile_claim_decision_failed",
                    retryable=False,
                )
            )
    return BatchClaimDecisionResource(items=items)


@router.post(
    "/api/profile/materials/{material_id}/deletion-preview",
    response_model=MaterialDeletionPreviewResource,
)
def preview_profile_material_deletion(
    material_id: str,
    command: MaterialDeletionPreviewCommand,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    application: AgentApplication = Depends(get_agent_application),
) -> MaterialDeletionPreviewResource:
    plan = application.profile(command.workspace_id).preview_material_deletion(
        material_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    claims = [AffectedClaimResource(**item) for item in plan.impact.get("claims", [])]
    return MaterialDeletionPreviewResource(
        deletion_plan_id=plan.id,
        material_id=plan.material_id,
        material_version=plan.material_version,
        expires_at=plan.expires_at,
        affected_evidence_count=len(plan.affected_evidence_ids),
        affected_claims=claims,
        unsupported_claim_ids=[
            item.claim_id for item in claims if not item.remaining_evidence_ids
        ],
        publication_selection_ids=list(plan.publication_selection_ids),
        active_publication_ids=list(plan.active_publication_ids),
    )


@router.post(
    "/api/profile/materials/{material_id}/permanent-delete",
    response_model=PermanentMaterialDeletionResource,
)
def permanently_delete_profile_material(
    material_id: str,
    command: PermanentMaterialDeletionCommand,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    application: AgentApplication = Depends(get_agent_application),
) -> PermanentMaterialDeletionResource:
    choices = {item.claim_id: item.action for item in command.claim_choices}
    if len(choices) != len(command.claim_choices):
        raise ProfileDeletionPlanConflict("duplicate claim deletion choice")
    result = application.profile(command.workspace_id).permanently_delete_material(
        material_id,
        deletion_plan_id=command.deletion_plan_id,
        expected_version=command.expected_version,
        claim_choices=choices,
        active_publication_action=command.active_publication_action,
        idempotency_key=idempotency_key,
    )
    return PermanentMaterialDeletionResource(
        plan_id=result.plan_id,
        status=result.status,
        items=[
            DeletionItemReceiptResource(
                kind=item.kind,
                target_id=item.target_id,
                status=item.status,
                action=item.action,
                error_code=item.error_code,
            )
            for item in result.items
        ],
    )


def _accepted_upload(result: MaterialUploadResult) -> AcceptedMaterialUploadResource:
    return AcceptedMaterialUploadResource(
        material_id=result.material.id,
        version_id=result.version.id,
        execution_id=result.execution_id,
        processing_status=result.accepted_processing_status,
    )


def _material_resource(
    service: ProfileService, material: ProfileMaterialRecord
) -> ProfileMaterialResource:
    versions = service.repository.list_material_versions(material.id)
    latest = versions[0] if versions else None
    return ProfileMaterialResource(
        id=material.id,
        workspace_id=material.workspace_id,
        type=material.type,
        title=material.title,
        primary_role=material.primary_role,
        current_version_id=material.current_version_id,
        lifecycle_status=material.lifecycle_status,
        version=material.version,
        version_count=len(versions),
        latest_processing_status=(
            None if latest is None else _effective_processing_status(service, latest)
        ),
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


def _version_resource(
    service: ProfileService, version: ProfileMaterialVersionRecord
) -> ProfileMaterialVersionResource:
    latest = service.product_repository.latest_execution(version.id)
    processing_status = _effective_processing_status(service, version, latest=latest)
    can_retry = processing_status in {"parse_failed", "extraction_failed"}
    if latest is not None and latest.status in {
        "queued", "running", "waiting_for_input", "waiting_for_approval"
    }:
        can_retry = False
    return ProfileMaterialVersionResource(
        id=version.id,
        material_id=version.material_id,
        version_number=version.version_number,
        source_type=version.source_type,
        file_name=version.file_name,
        mime_type=version.mime_type,
        processing_status=processing_status,
        stages=_processing_stages(processing_status),
        can_retry=can_retry,
        created_at=version.created_at,
    )


def _effective_processing_status(
    service: ProfileService,
    version: ProfileMaterialVersionRecord,
    *,
    latest=None,
) -> str:
    """Project stale pre-fix ingest failures as retryable terminal states."""
    if version.processing_status in {
        "ready",
        "parse_failed",
        "extraction_failed",
    }:
        return version.processing_status
    execution = latest or service.product_repository.latest_execution(version.id)
    if execution is None or execution.status not in {
        "failed",
        "interrupted",
        "cancelled",
    }:
        return version.processing_status
    if version.processing_status in {"uploaded", "parsing"}:
        return "parse_failed"
    return "extraction_failed"


def _processing_stages(status_value: str) -> list[MaterialProcessingStageResource]:
    keys = ("uploaded", "parsing", "parsed", "extracting", "ready")
    labels = ("已上传", "提取文本", "隐私处理", "生成画像建议", "等待确认")
    failed_key = {
        "parse_failed": "parsing",
        "extraction_failed": "extracting",
    }.get(status_value)
    current_key = failed_key or status_value
    current_index = keys.index(current_key)
    result = []
    for index, (key, label) in enumerate(zip(keys, labels, strict=True)):
        stage_status = "completed" if index < current_index else "pending"
        if index == current_index:
            stage_status = "failed" if failed_key else (
                "completed" if status_value == "ready" else "active"
            )
        result.append(MaterialProcessingStageResource(key=key, label=label, status=stage_status))
    return result


def _evidence_resource(evidence: EvidenceRecord) -> ProfileEvidenceResource:
    try:
        locator = json.loads(evidence.section)
        if not isinstance(locator, dict):
            locator = {"section": evidence.section}
    except json.JSONDecodeError:
        locator = {"section": evidence.section}
    return ProfileEvidenceResource(
        id=evidence.id,
        material_version_id=evidence.material_version_id,
        locator=locator,
        start_offset=evidence.start_offset,
        end_offset=evidence.end_offset,
        excerpt=evidence.sanitized_text[:2000],
        sensitivity=evidence.sensitivity,
        created_at=evidence.created_at,
    )


def _claim_version_resource(
    version: ProfileClaimVersionRecord,
) -> ClaimVersionResource:
    return ClaimVersionResource(
        id=version.id,
        claim_id=version.claim_id,
        version=version.version,
        value=version.value,
        status=version.status,
        support_status=version.support_status,
        evidence_ids=list(version.evidence_ids),
        source=version.source,
        expected_previous_version=version.expected_previous_version,
        created_at=version.created_at,
        confirmed_at=version.confirmed_at,
    )


def _proposal_resource(
    service: ProfileService, proposal: ClaimProposalRecord
) -> ClaimProposalResource:
    return ClaimProposalResource(
        id=proposal.id,
        proposal_type=proposal.proposal_type,
        target_claim_id=proposal.target_claim_id,
        base_claim_version_id=proposal.base_claim_version_id,
        proposed_value=proposal.proposed_value,
        reason=proposal.reason,
        status=proposal.status,
        evidence=[
            _evidence_resource(service.repository.get_evidence(evidence_id))
            for evidence_id in proposal.evidence_ids
        ],
        decided_at=proposal.decided_at,
        created_at=proposal.created_at,
    )


def _claim_review_resource(
    service: ProfileService, detail: ClaimReviewDetail
) -> ClaimReviewResource:
    return ClaimReviewResource(
        id=detail.claim.id,
        claim_type=detail.claim.claim_type,
        version=detail.claim.version,
        current_version=_claim_version_resource(detail.current_version),
        versions=[_claim_version_resource(item) for item in detail.versions],
        proposals=[_proposal_resource(service, item) for item in detail.proposals],
        conflicts=[
            ClaimConflictResource(
                id=item.id,
                proposal_id=item.proposal_id,
                conflicting_claim_version_id=item.conflicting_claim_version_id,
                created_at=item.created_at,
            )
            for item in detail.conflicts
        ],
        evidence=[_evidence_resource(item) for item in detail.evidence],
        created_at=detail.claim.created_at,
        updated_at=detail.claim.updated_at,
    )


def _decision_resource(result: ClaimDecisionResult) -> ClaimDecisionResource:
    return ClaimDecisionResource(
        proposal_id=result.proposal_id,
        status=result.status,
        claim_id=result.claim_id,
        claim_version_id=result.claim_version_id,
        support_status=result.support_status,
    )


def _action_plan_resource(
    service: ProfileService, plan: ProfileActionPlanRecord
) -> ProfileActionPlanResource:
    current_version = service.repository.profile_snapshot(
        service.workspace_id
    ).profile_version
    stale = plan.base_profile_version != (current_version or "")
    return ProfileActionPlanResource(
        id=plan.id,
        workspace_id=plan.workspace_id,
        session_id=plan.session_id,
        execution_id=plan.execution_id,
        request_summary=plan.request_summary,
        base_profile_version=plan.base_profile_version,
        current_profile_version=current_version,
        selection_snapshot=plan.selection_snapshot,
        items=[
            ProfileActionPlanItemResource(
                item_id=item.item_id,
                ordinal=item.ordinal,
                operation=item.operation,
                target=item.target,
                expected_version=item.expected_version,
                before=item.before,
                after=item.after,
                evidence_ids=list(item.evidence_ids),
                status=item.status,
                receipt_id=item.receipt_id,
                error_code=item.error_code,
            )
            for item in plan.items
        ],
        status=plan.status,
        version=plan.version,
        stale=stale,
        can_confirm=not stale and plan.status in {"validated", "awaiting_confirmation"},
        can_cancel=plan.status in {"proposed", "validated", "awaiting_confirmation"},
        retryable=not stale and plan.status in {"failed", "partially_completed"},
        expires_at=plan.expires_at,
        created_at=plan.created_at,
        confirmed_at=plan.confirmed_at,
        completed_at=plan.completed_at,
    )
