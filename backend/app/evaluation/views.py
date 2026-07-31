from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.contracts import EvaluationApplicability
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
    terminal_state: str
    dimensions: tuple[EvaluationDimensionInput, ...]
    counters: dict[str, dict[str, int]]
    items: tuple[EvaluationViewItem, ...]
    evidence_gaps: tuple[str, ...]
    data_categories: tuple[str, ...]


_QUESTION_CONTENT_FIELDS = (
    "question_text",
    "reference_answer",
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
        if provenance.field_path == "content.referenceAnswer"
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
