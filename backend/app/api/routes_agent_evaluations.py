from __future__ import annotations

import json
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
    if not command.include_private_bodies:
        for event in snapshot.get("events", []):
            if isinstance(event, dict):
                event["content"] = None
                event["available"] = False
    case = service.repository.create_regression_case(
        case_id=str(uuid4()),
        source_eval_run_id=record.id,
        execution_id=record.execution_id,
        eval_pack_id=record.eval_pack_id,
        eval_pack_version=record.eval_pack_version,
        snapshot_hash=record.frozen_input_hash,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        expected_invariants_json=json.dumps(
            command.expected_invariants, ensure_ascii=False
        ),
        contains_private_bodies=command.include_private_bodies,
        redaction_summary=(
            "保留冻结 Trace 正文"
            if command.include_private_bodies
            else "已移除冻结 Trace 正文，仅保留元数据和哈希"
        ),
    )
    return case


@router.get("/regression-cases", response_model=RegressionCaseListResource)
async def list_regression_cases(
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    return {"items": service.repository.list_regression_cases()}


@router.post("/regression-runs", response_model=EvaluationRunResource, status_code=201)
async def create_regression_run(
    command: CreateRegressionRunCommand,
    service: AgentEvaluationService = Depends(get_agent_evaluation_service),
):
    case = next(
        (
            item
            for item in service.repository.list_regression_cases()
            if item.id == command.case_id
        ),
        None,
    )
    if case is None:
        return _error(404, "regression_case_not_found", "回归样例不存在或无权访问")
    record = await service.evaluate(
        case.execution_id,
        trigger="regression",
        idempotency_key=f"regression:{case.id}:{case.version}",
    )
    return _run_resource(service, record)


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
