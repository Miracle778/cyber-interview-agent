from __future__ import annotations

import json
import hashlib
import re
from dataclasses import asdict
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse

from app.api.dependencies import get_agent_evaluation_service
from app.evaluation.service import (
    AgentEvaluationService,
    EvaluationNotSupportedError,
)
from app.evaluation.case_snapshot import create_restorable_case_snapshot
from app.schemas.evaluation import (
    CreateEvaluationFeedbackCommand,
    CreateEvaluationRunCommand,
    CreateRegressionCaseCommand,
    CreateRegressionRunCommand,
    EvaluationComparisonResource,
    EvaluationFeedbackResource,
    EvaluationRunListResource,
    EvaluationRunResource,
    RegressionCaseListResource,
    RegressionCaseResource,
    RegressionRunListResource,
    RegressionRunResource,
    EvaluationTrendListResource,
)
from app.evaluation.trends import EvaluationTrendService


router = APIRouter(prefix="/api/agent-evaluations", tags=["agent-evaluations"])


@router.get("/trends", response_model=EvaluationTrendListResource)
async def get_evaluation_trends(
    graph_id: Annotated[str | None, Query(alias="graphId")] = None,
    eval_pack_id: Annotated[str | None, Query(alias="evalPackId")] = None,
    eval_pack_version: Annotated[int | None, Query(alias="evalPackVersion")] = None,
    judge_provider_model_id: Annotated[
        str | None, Query(alias="judgeProviderModelId")
    ] = None,
    started_from: Annotated[str | None, Query(alias="startedFrom")] = None,
    started_to: Annotated[str | None, Query(alias="startedTo")] = None,
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    trends = EvaluationTrendService(
        service.repository.connection,
        service.workspace_id,
    ).query(
        graph_id=graph_id,
        eval_pack_id=eval_pack_id,
        eval_pack_version=eval_pack_version,
        judge_provider_model_id=judge_provider_model_id,
        started_from=started_from,
        started_to=started_to,
    )
    return {"items": trends}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})


def _json(value: str | None):
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _redact_case_value(value, *, include_private_bodies: bool):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized = str(key).casefold().replace("_", "")
            if any(token in normalized for token in (
                "password", "secret", "apikey", "accesstoken", "refreshtoken",
                "workspacepath", "localpath", "storageref",
            )):
                continue
            redacted[str(key)] = _redact_case_value(
                item, include_private_bodies=include_private_bodies
            )
        return redacted
    if isinstance(value, list):
        return [
            _redact_case_value(item, include_private_bodies=include_private_bodies)
            for item in value
        ]
    if isinstance(value, str) and not include_private_bodies:
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[已隐藏邮箱]", value)
        value = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[已隐藏手机号]", value)
    return value


def _run_resource(service: AgentEvaluationService, record) -> EvaluationRunResource:
    advanced = service.advanced_diagnostics_enabled
    dimensions = []
    for item in service.repository.list_dimension_results(record.id):
        dimensions.append(
            {
                "dimension_id": item.dimension_id,
                "source": item.source,
                "status": item.status,
                "applicability": item.applicability,
                "rating": item.rating,
                "severity": item.severity,
                "score": item.score,
                "confidence": item.confidence,
                "summary": item.summary,
                "cited_event_hashes": _json(item.cited_event_hashes_json) or [],
                "cited_artifact_hashes": _json(item.cited_artifact_hashes_json) or [],
                "risks": _json(item.risks_json) or [],
                "evidence_gaps": _json(item.evidence_gaps_json) or [],
                "evidence_refs": _json(item.evidence_refs_json) or [],
            }
        )
    judged = _json(record.judge_result_json)
    judge_summary = None
    if isinstance(judged, dict):
        judge_summary = {
            key: judged.get(key)
            for key in (
                "confidence",
                "summary",
                "risks",
                "humanReviewRequired",
            )
        }
    values = asdict(record)
    values.pop("judge_trace_run_id", None)
    values.pop("judge_data_scope_json", None)
    return EvaluationRunResource(
        **values,
        judge_data_scope=_json(record.judge_data_scope_json) or {},
        dimensions=dimensions,
        deterministic_result=_json(record.deterministic_result_json),
        judge_summary=judge_summary,
        judge_trace_run_id=record.judge_trace_run_id if advanced else None,
        raw_snapshot=_json(record.snapshot_json) if advanced else None,
        raw_judge_result=judged if advanced else None,
    )


def _case_resource(service: AgentEvaluationService, record) -> RegressionCaseResource:
    privacy_manifest = _json(record.privacy_manifest_json) or {}
    baseline_versions = _json(record.baseline_versions_json) or {}
    implementation_ids = tuple(
        getattr(service, "regression_implementation_ids", ())
    )
    runnable = (
        record.case_contract_version >= 2
        and privacy_manifest.get("domainSnapshotMode") == "restorable"
        and len(implementation_ids) >= 2
    )
    return RegressionCaseResource(
        id=record.id,
        execution_id=record.execution_id,
        eval_pack_id=record.eval_pack_id,
        eval_pack_version=record.eval_pack_version,
        version=record.version,
        snapshot_hash=record.snapshot_hash,
        contains_private_bodies=record.contains_private_bodies,
        redaction_summary=record.redaction_summary,
        case_contract_version=record.case_contract_version,
        task_type=record.task_type,
        privacy_manifest=privacy_manifest,
        baseline_versions=baseline_versions,
        runnable=runnable,
        unavailable_reason=(
            None
            if runnable
            else (
                "当前案例缺少可恢复的执行前领域快照"
                if privacy_manifest.get("domainSnapshotMode") != "restorable"
                else "当前进程未注册可同时运行的基线与候选 Agent 实现"
            )
        ),
        available_implementation_ids=list(implementation_ids),
        created_at=record.created_at,
    )


def _regression_run_resource(record) -> RegressionRunResource:
    return RegressionRunResource(
        id=record.id,
        case_id=record.case_id,
        case_version=record.case_version,
        status=record.status,
        baseline_implementation_id=record.baseline_implementation_id,
        candidate_implementation_id=record.candidate_implementation_id,
        baseline_execution_id=record.baseline_execution_id,
        candidate_execution_id=record.candidate_execution_id,
        baseline_outcome_hash=record.baseline_outcome_hash,
        candidate_outcome_hash=record.candidate_outcome_hash,
        deterministic_comparison=_json(record.deterministic_comparison_json),
        pairwise_result=_json(record.pairwise_result_json),
        infrastructure_failures=_json(record.infrastructure_failures_json) or [],
        isolation_manifest=_json(record.isolation_manifest_json) or {},
        error_code=record.error_code,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


@router.post("/runs", response_model=EvaluationRunResource, status_code=201)
async def create_evaluation_run(
    command: CreateEvaluationRunCommand,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    try:
        record = await service.evaluate(
            command.execution_id,
            trigger="manual",
            idempotency_key=idempotency_key,
            eval_pack_id=command.eval_pack_id,
        )
    except EvaluationNotSupportedError as error:
        return _error(422, "evaluation_not_supported", str(error))
    except LookupError:
        return _error(404, "execution_not_found", "Agent Execution 不存在或无权访问")
    return _run_resource(service, record)


@router.get("/runs", response_model=EvaluationRunListResource)
async def list_evaluation_runs(
    execution_id: Annotated[str | None, Query(alias="executionId")] = None,
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    records = (
        service.repository.list_runs()
        if execution_id is None
        else service.repository.list_runs_for_execution(execution_id)
    )
    return {"items": [_run_resource(service, item) for item in records]}


@router.get("/runs/{eval_run_id}", response_model=EvaluationRunResource)
async def get_evaluation_run(
    eval_run_id: str,
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    record = service.repository.get_run(eval_run_id)
    if record is None:
        return _error(404, "evaluation_run_not_found", "评估运行不存在或无权访问")
    return _run_resource(service, record)


@router.post(
    "/runs/{eval_run_id}/feedback",
    response_model=EvaluationFeedbackResource,
    status_code=201,
)
async def create_evaluation_feedback(
    eval_run_id: str,
    command: CreateEvaluationFeedbackCommand,
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    try:
        return service.repository.add_feedback(
            eval_run_id=eval_run_id,
            feedback_id=str(uuid4()),
            verdict=command.verdict,
            dimension_id=command.dimension_id,
            reason=command.reason,
        )
    except LookupError:
        return _error(404, "evaluation_run_not_found", "评估运行不存在或无权访问")


@router.get(
    "/runs/{eval_run_id}/feedback",
    response_model=list[EvaluationFeedbackResource],
)
async def list_evaluation_feedback(
    eval_run_id: str,
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    return service.repository.list_feedback(eval_run_id)


@router.post(
    "/regression-cases",
    response_model=RegressionCaseResource,
    status_code=201,
)
async def create_regression_case(
    command: CreateRegressionCaseCommand,
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    if not command.confirmed:
        return _error(409, "regression_confirmation_required", "请确认冻结字段后再创建")
    record = service.repository.get_run(command.eval_run_id)
    if record is None:
        return _error(404, "evaluation_run_not_found", "评估运行不存在或无权访问")
    snapshot = _json(record.snapshot_json) or {}
    execution_row = service.repository.connection.execute(
        "SELECT input_json, configuration_json, model_bindings_json "
        "FROM agent_runs WHERE id = ?",
        (record.execution_id,),
    ).fetchone()
    raw_input = _json(execution_row["input_json"]) if execution_row else {}
    configuration = _json(execution_row["configuration_json"]) if execution_row else {}
    model_bindings = _json(execution_row["model_bindings_json"]) if execution_row else {}
    sanitized_input = _redact_case_value(
        raw_input or {}, include_private_bodies=command.include_private_bodies
    )
    business_outcome = snapshot.get("businessOutcome") if isinstance(snapshot, dict) else None
    case_id = str(uuid4())
    required_domain_snapshot = {
        "mode": "projection_only",
        "identity": (
            business_outcome.get("identity", {})
            if isinstance(business_outcome, dict)
            else {}
        ),
        "sourceRefs": (
            business_outcome.get("input", {}).get("sourceRefs", [])
            if isinstance(business_outcome, dict)
            and isinstance(business_outcome.get("input"), dict)
            else []
        ),
    }
    if command.include_private_bodies:
        pre_execution = service.pre_execution_snapshot(record.execution_id)
        if pre_execution is not None:
            required_domain_snapshot = {
                **pre_execution,
                "identity": required_domain_snapshot["identity"],
                "sourceRefs": required_domain_snapshot["sourceRefs"],
            }
        else:
            restorable = create_restorable_case_snapshot(
                workspace_root=service.workspace_root,
                case_id=case_id,
                connection=service.repository.connection,
            )
            required_domain_snapshot = {
                **restorable,
                "mode": "post_execution_archive",
                "identity": required_domain_snapshot["identity"],
                "sourceRefs": required_domain_snapshot["sourceRefs"],
            }
    baseline_versions = {
        "evalPack": f"{record.eval_pack_id}@{record.eval_pack_version}",
        "evaluationContract": record.evaluation_contract_version,
        "runtime": (
            business_outcome.get("runtimeVersions", {})
            if isinstance(business_outcome, dict)
            else {}
        ),
        "executionConfiguration": configuration or {},
        "modelBindings": model_bindings or {},
    }
    privacy_manifest = {
        "containsPrivateBodies": command.include_private_bodies,
        "redactions": ["secrets", "localPaths"] + (
            [] if command.include_private_bodies else ["email", "phone"]
        ),
        "dataCategories": ["taskInput", "domainRefs", "businessOutcome"],
        "domainSnapshotMode": required_domain_snapshot["mode"],
    }
    case_payload = {
        "contractVersion": 2 if record.evaluation_contract_version >= 2 else 1,
        "taskType": record.task_type,
        "sanitizedInput": sanitized_input,
        "requiredDomainSnapshot": required_domain_snapshot,
        "expectedInvariants": command.expected_invariants,
        "privacyManifest": privacy_manifest,
        "baselineVersions": baseline_versions,
        "sourceBusinessOutcome": business_outcome,
    }
    canonical_case = json.dumps(
        case_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    case = service.repository.create_regression_case(
        case_id=case_id,
        source_eval_run_id=record.id,
        execution_id=record.execution_id,
        eval_pack_id=record.eval_pack_id,
        eval_pack_version=record.eval_pack_version,
        snapshot_hash=hashlib.sha256(canonical_case.encode("utf-8")).hexdigest(),
        snapshot_json=canonical_case,
        expected_invariants_json=json.dumps(
            command.expected_invariants, ensure_ascii=False
        ),
        contains_private_bodies=command.include_private_bodies,
        redaction_summary=(
            "保留经确认的任务正文；Secret 与本地路径仍已移除"
            if command.include_private_bodies
            else "已隐藏邮箱、手机号、Secret 与本地路径"
        ),
        case_contract_version=case_payload["contractVersion"],
        task_type=record.task_type,
        sanitized_input_json=json.dumps(
            sanitized_input, ensure_ascii=False, sort_keys=True
        ),
        required_domain_snapshot_json=json.dumps(
            required_domain_snapshot, ensure_ascii=False, sort_keys=True
        ),
        privacy_manifest_json=json.dumps(
            privacy_manifest, ensure_ascii=False, sort_keys=True
        ),
        baseline_versions_json=json.dumps(
            baseline_versions, ensure_ascii=False, sort_keys=True
        ),
        source_business_outcome_json=(
            None
            if business_outcome is None
            else json.dumps(business_outcome, ensure_ascii=False, sort_keys=True)
        ),
    )
    return _case_resource(service, case)


@router.get("/regression-cases", response_model=RegressionCaseListResource)
async def list_regression_cases(
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    return {
        "items": [
            _case_resource(service, item)
            for item in service.repository.list_regression_cases()
        ]
    }


@router.post("/regression-runs", response_model=RegressionRunResource, status_code=201)
async def create_regression_run(
    command: CreateRegressionRunCommand,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    case = service.repository.get_regression_case(command.case_id)
    if case is None:
        return _error(404, "regression_case_not_found", "回归样例不存在或无权访问")
    try:
        record = await service.run_regression_case(
            case_id=case.id,
            baseline_implementation_id=command.baseline_implementation_id,
            candidate_implementation_id=command.candidate_implementation_id,
            idempotency_key=idempotency_key,
        )
    except EvaluationNotSupportedError as error:
        return _error(422, "regression_not_supported", str(error))
    return _regression_run_resource(record)


@router.get("/regression-runs", response_model=RegressionRunListResource)
async def list_regression_runs(
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    return {
        "items": [
            _regression_run_resource(item)
            for item in service.repository.list_regression_runs()
        ]
    }


@router.get("/comparisons", response_model=EvaluationComparisonResource)
async def compare_evaluation_runs(
    run_ids: Annotated[list[str], Query(alias="runId")],
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    records = [service.repository.get_run(run_id) for run_id in run_ids]
    if not records or any(item is None for item in records):
        return _error(404, "evaluation_run_not_found", "评估运行不存在或无权访问")
    concrete = [item for item in records if item is not None]
    identities = {(item.eval_pack_id, item.eval_pack_version) for item in concrete}
    dimension_sets = [
        {
            item.dimension_id
            for item in service.repository.list_dimension_results(record.id)
            if item.source == "judge"
        }
        for record in concrete
    ]
    if len(identities) != 1 or any(
        dimensions != dimension_sets[0] for dimensions in dimension_sets[1:]
    ):
        return _error(
            409,
            "evaluation_comparison_incompatible",
            "评估版本或维度不兼容，不能直接比较",
        )
    pack_id, version = next(iter(identities))
    return {
        "eval_pack_id": pack_id,
        "eval_pack_version": version,
        "dimension_ids": sorted(dimension_sets[0]),
        "runs": [_run_resource(service, item) for item in concrete],
    }
