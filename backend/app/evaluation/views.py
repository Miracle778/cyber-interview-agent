from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.contracts import EvalPack, EvaluationApplicability
from app.evaluation.outcomes import BusinessOutcomeProjection


class EvaluationViewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvaluationDimensionInput(EvaluationViewModel):
    dimension_id: str
    applicability: EvaluationApplicability
    applicability_reason: str


class EvaluationViewItem(EvaluationViewModel):
    item_id: str
    status: str
    content: dict[str, object]
    provenance: tuple[dict[str, object], ...]
    user_decision: dict[str, object]


class EvaluationView(EvaluationViewModel):
    view_version: int = Field(default=1, ge=1)
    task_type: str
    business_outcome_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: dict[str, object]
    requested_scope: dict[str, object]
    terminal_state: str
    dimensions: tuple[EvaluationDimensionInput, ...]
    counters: dict[str, dict[str, int]]
    items: tuple[EvaluationViewItem, ...]
    evidence_gaps: tuple[str, ...]
    data_categories: tuple[str, ...]


_QUESTION_CONTENT_FIELDS = (
    "question_text",
    "reference_answer",
    "source_answer",
    "supplemental_answer",
    "topics",
    "difficulty",
    "key_points",
    "follow_ups",
    "answer_basis",
    "material_support",
    "needs_review",
    "normalization_issues",
    "source_refs",
)


def build_question_curation_evaluation_view(
    outcome: BusinessOutcomeProjection,
) -> EvaluationView:
    if outcome.task_type != "question_curation":
        raise ValueError("question-curation view requires a question-curation outcome")
    items = tuple(
        EvaluationViewItem(
            item_id=item.item_id,
            status=item.status,
            content={
                key: item.content[key]
                for key in _QUESTION_CONTENT_FIELDS
                if key in item.content
            },
            provenance=tuple(
                {
                    "fieldPath": provenance.field_path,
                    "supportType": provenance.support_type,
                    "sourceRefs": provenance.source_refs,
                    "evidenceRefs": provenance.evidence_refs,
                    "note": provenance.note,
                }
                for provenance in item.provenance
            ),
            user_decision=item.user_decision.model_dump(mode="json"),
        )
        for item in outcome.items
    )
    has_items = bool(items)
    answer_support = {
        provenance.support_type
        for item in outcome.items
        for provenance in item.provenance
        if provenance.field_path in {
            "content.referenceAnswer",
            "content.sourceAnswer",
            "content.supplementalAnswer",
        }
    }
    dimensions = (
        _dimension(
            "material_processing_completeness",
            "applicable" if outcome.units else "insufficient_evidence",
            "存在可核对的处理单元" if outcome.units else "没有处理单元明细",
        ),
        _dimension(
            "explicit_question_recognition",
            "insufficient_evidence",
            "当前结果没有保存材料中明确题目的可靠分母",
        ),
        _dimension(
            "candidate_completeness",
            "applicable" if has_items else "not_applicable",
            "存在候选题" if has_items else "本次没有候选题",
        ),
        _dimension(
            "question_source_consistency",
            "applicable" if has_items else "not_applicable",
            "存在需要核对来源表达的候选题" if has_items else "本次没有候选题",
        ),
        _dimension(
            "source_answer_fidelity",
            (
                "insufficient_evidence"
                if "source_supplemental_answer_not_separated" in outcome.evidence_gaps
                else "applicable"
                if "direct" in answer_support
                else "not_applicable"
            ),
            (
                "原文答案与模型补充已合并，无法独立评价"
                if "source_supplemental_answer_not_separated" in outcome.evidence_gaps
                else "存在声称直接来自材料的答案"
                if "direct" in answer_support
                else "材料未提供原文答案"
            ),
        ),
        _dimension(
            "model_completion_quality",
            "applicable" if "inferred" in answer_support else "not_applicable",
            "存在模型补充答案" if "inferred" in answer_support else "没有模型补充答案",
        ),
        _dimension(
            "completion_transparency",
            "applicable" if "inferred" in answer_support else "not_applicable",
            "存在需要向用户标识的模型补充" if "inferred" in answer_support else "没有模型补充",
        ),
        _dimension(
            "duplicate_handling",
            "insufficient_evidence",
            "当前结果未保存疑似重复召回和最终关系判定",
        ),
        _dimension(
            "zero_result_reasoning",
            "not_applicable" if has_items else "applicable",
            "已有候选题" if has_items else "需要判断零结果是否合理",
        ),
    )
    return EvaluationView(
        task_type=outcome.task_type,
        business_outcome_hash=outcome.outcome_hash,
        identity={
            "executionId": outcome.identity.execution_id,
            "graphId": outcome.identity.graph_id,
            "domainRefs": outcome.identity.domain_refs,
        },
        requested_scope=outcome.input.requested_scope,
        terminal_state=outcome.terminal_state,
        dimensions=dimensions,
        counters={
            name: counters.model_dump(mode="json")
            for name, counters in outcome.unit_counters.items()
        },
        items=items,
        evidence_gaps=outcome.evidence_gaps,
        data_categories=(
            "taskIdentity",
            "curationCounters",
            "candidateContent",
            "fieldProvenance",
            "userDecision",
            "evidenceGaps",
        ),
    )


def build_task_evaluation_view(
    outcome: BusinessOutcomeProjection,
    pack: EvalPack,
) -> EvaluationView:
    if pack.task_type != outcome.task_type:
        raise ValueError("outcome and Eval Pack task types do not match")
    if pack.task_type == "question_curation":
        return build_question_curation_evaluation_view(outcome)
    policy = pack.judge_view
    if policy is None:
        raise ValueError("v2 Eval Pack must declare a Judge View policy")
    selected = outcome.items[: policy.max_items]
    items = tuple(
        EvaluationViewItem(
            item_id=item.item_id,
            status=item.status,
            content={
                key: _limit_value(item.content[key], policy.max_text_chars)
                for key in policy.content_fields
                if key in item.content
            },
            provenance=tuple(
                {
                    "fieldPath": provenance.field_path,
                    "supportType": provenance.support_type,
                    "sourceRefs": provenance.source_refs,
                    "evidenceRefs": provenance.evidence_refs,
                    "note": provenance.note,
                }
                for provenance in item.provenance
            ),
            user_decision=item.user_decision.model_dump(mode="json"),
        )
        for item in selected
    )
    dimensions = tuple(
        _generic_applicability(dimension.id, outcome)
        for dimension in pack.dimensions
    )
    gaps = list(outcome.evidence_gaps)
    if len(outcome.items) > policy.max_items:
        gaps.append("judge_view_items_truncated")
    return EvaluationView(
        task_type=outcome.task_type,
        business_outcome_hash=outcome.outcome_hash,
        identity={
            "executionId": outcome.identity.execution_id,
            "graphId": outcome.identity.graph_id,
            "domainRefs": outcome.identity.domain_refs,
        },
        requested_scope=outcome.input.requested_scope,
        terminal_state=outcome.terminal_state,
        dimensions=dimensions,
        counters={
            name: counters.model_dump(mode="json")
            for name, counters in outcome.unit_counters.items()
        },
        items=items,
        evidence_gaps=tuple(dict.fromkeys(gaps)),
        data_categories=policy.data_categories,
    )


def _generic_applicability(
    dimension_id: str,
    outcome: BusinessOutcomeProjection,
) -> EvaluationDimensionInput:
    has_items = bool(outcome.items)
    contents = [item.content for item in outcome.items]
    if "conflict" in dimension_id:
        has_conflict = any(
            content.get("conflict_ids") or content.get("relation")
            for content in contents
        )
        return _dimension(
            dimension_id,
            "applicable" if has_conflict else "not_applicable",
            "存在冲突关系" if has_conflict else "本次没有冲突关系",
        )
    if dimension_id in {"tool_necessity", "tool_usefulness"}:
        has_tools = any(unit.unit_type.startswith("tool:") for unit in outcome.units)
        return _dimension(
            dimension_id,
            "applicable" if has_tools else "not_applicable",
            "本次调用了 Tool" if has_tools else "本次没有 Tool 调用",
        )
    if dimension_id in {"follow_up_decision", "follow_up_wording"}:
        has_follow_up = any(
            content.get("follow_up_answer")
            or "follow" in str(content.get("evaluation", "")).casefold()
            for content in contents
        )
        return _dimension(
            dimension_id,
            "applicable" if has_follow_up else "not_applicable",
            "本次存在追问" if has_follow_up else "本次没有追问",
        )
    if dimension_id == "assistance_boundary":
        assisted = any(
            int(content.get("hint_level") or 0) > 0
            or content.get("result_kind") in {"assisted_mastery", "revealed"}
            for content in contents
        )
        return _dimension(
            dimension_id,
            "applicable" if assisted else "not_applicable",
            "本次使用了提示或查看答案" if assisted else "本次未使用辅助",
        )
    if not has_items:
        return _dimension(
            dimension_id,
            "insufficient_evidence",
            "没有可评价的最终业务结果项",
        )
    if dimension_id in {"source_offsets", "version_traceability"} and any(
        content.get("locator_valid") is None for content in contents
    ):
        return _dimension(
            dimension_id,
            "insufficient_evidence",
            "缺少可反查的文档 offset 或版本正文",
        )
    return _dimension(dimension_id, "applicable", "存在可评价的业务结果")


def _limit_value(value: object, max_text_chars: int) -> object:
    if isinstance(value, str):
        return value if len(value) <= max_text_chars else value[:max_text_chars]
    if isinstance(value, list):
        return [_limit_value(item, max_text_chars) for item in value[:100]]
    if isinstance(value, tuple):
        return tuple(_limit_value(item, max_text_chars) for item in value[:100])
    if isinstance(value, dict):
        return {
            str(key): _limit_value(item, max_text_chars)
            for key, item in list(value.items())[:100]
            if not _sensitive_key(str(key))
        }
    return value


def _sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("_", "")
    return any(
        token in normalized
        for token in (
            "password", "secret", "apikey", "accesstoken", "refreshtoken",
            "storageref", "textref", "workspacepath", "localpath",
        )
    )


def _dimension(
    dimension_id: str,
    applicability: EvaluationApplicability,
    reason: str,
) -> EvaluationDimensionInput:
    return EvaluationDimensionInput(
        dimension_id=dimension_id,
        applicability=applicability,
        applicability_reason=reason,
    )
