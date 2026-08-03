from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class RetrospectiveAgentModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class CleanupSegment(RetrospectiveAgentModel):
    ordinal: int = Field(ge=1)
    speaker_role: Literal["candidate", "interviewer", "unknown"]
    raw_speaker_label: str | None = Field(default=None, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=24_000)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    uncertainty_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_offsets(self) -> "CleanupSegment":
        if self.source_end <= self.source_start:
            raise ValueError("sourceEnd 必须大于 sourceStart")
        return self


class CleanupCorrection(RetrospectiveAgentModel):
    segment_ordinal: int = Field(ge=1)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    original_text: str = Field(min_length=1, max_length=24_000)
    suggested_text: str | None = Field(default=None, max_length=24_000)
    change_type: Literal["formatting", "recognition", "semantic"]
    risk_level: Literal["low", "high"]
    reason: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_offsets(self) -> "CleanupCorrection":
        if self.source_end <= self.source_start:
            raise ValueError("sourceEnd 必须大于 sourceStart")
        if self.suggested_text is None and self.risk_level != "high":
            raise ValueError("没有安全建议的修订必须标记为高风险")
        return self


class MaterializedCleanupOutput(RetrospectiveAgentModel):
    segments: list[CleanupSegment] = Field(default_factory=list, max_length=500)
    corrections: list[CleanupCorrection] = Field(default_factory=list, max_length=1_000)

    @model_validator(mode="after")
    def validate_segment_order(self) -> "MaterializedCleanupOutput":
        previous_end = -1
        for segment in self.segments:
            if segment.source_start < previous_end:
                raise ValueError("片段 offset 必须有序且不重叠")
            previous_end = segment.source_end
        return self

    def validate_window(
        self,
        *,
        source_start: int,
        source_end: int,
        emit_start: int | None = None,
        source_body: str | None = None,
    ) -> None:
        if source_start < 0 or source_end <= source_start:
            raise ValueError("当前文字窗口无效")
        effective_emit_start = source_start if emit_start is None else emit_start
        if not source_start <= effective_emit_start < source_end:
            raise ValueError("当前文字窗口允许输出范围无效")
        if any(
            segment.source_start < source_start or segment.source_end > source_end
            for segment in self.segments
        ):
            raise ValueError("整理片段不属于当前文字窗口")
        if any(
            segment.source_start < effective_emit_start for segment in self.segments
        ):
            raise ValueError("整理片段超出当前文字窗口允许输出范围")
        previous_correction_end = -1
        segment_ordinals = {segment.ordinal for segment in self.segments}
        for correction in sorted(
            self.corrections,
            key=lambda item: (item.source_start, item.source_end),
        ):
            if (
                correction.source_start < effective_emit_start
                or correction.source_end > source_end
            ):
                raise ValueError("修订原文不属于当前文字窗口")
            if correction.segment_ordinal not in segment_ordinals:
                raise ValueError("修订原文没有对应的整理片段")
            if correction.source_start < previous_correction_end:
                raise ValueError("修订范围不能重叠")
            previous_correction_end = correction.source_end
            if source_body is not None:
                local_start = correction.source_start - source_start
                local_end = correction.source_end - source_start
                if source_body[local_start:local_end] != correction.original_text:
                    raise ValueError("修订原文必须与不可变原文完全一致")


class CleanupTurnOutput(RetrospectiveAgentModel):
    source_text: str | None = Field(default=None, min_length=1, max_length=2_000)
    speaker_role: Literal["candidate", "interviewer", "unknown"]
    raw_speaker_label: str | None = Field(default=None, max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    corrected_text: str = Field(min_length=1, max_length=2_000)
    confidence: float = Field(ge=0, le=1)
    uncertainty_reason: str | None = Field(default=None, max_length=500)


class CleanupUnitOutput(RetrospectiveAgentModel):
    unit_id: str | None = Field(default=None, min_length=1, max_length=128)
    turns: list[CleanupTurnOutput] = Field(min_length=1, max_length=40)


class CleanupOutput(RetrospectiveAgentModel):
    """Compact model-facing result grounded by program-owned source units."""

    units: list[CleanupUnitOutput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_unique_units(self) -> "CleanupOutput":
        unit_ids = [unit.unit_id for unit in self.units if unit.unit_id is not None]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("unitId 不能重复")
        return self

    def validate_units(self, *, expected_unit_ids: tuple[str, ...]) -> None:
        if len(self.units) != len(expected_unit_ids):
            raise ValueError("整理结果必须完整返回当前窗口的 sourceUnits")
        for unit, expected_unit_id in zip(
            self.units,
            expected_unit_ids,
            strict=True,
        ):
            if unit.unit_id is None:
                unit.unit_id = expected_unit_id
        actual_unit_ids = tuple(unit.unit_id for unit in self.units)
        if actual_unit_ids != expected_unit_ids:
            raise ValueError("整理结果必须按顺序完整返回当前窗口的 sourceUnits")


class CleanupUncertainItem(RetrospectiveAgentModel):
    excerpt: str = Field(min_length=1, max_length=500)
    possible_value: str | None = Field(default=None, max_length=500)
    issue_kind: Literal["uncertain_term", "speaker", "semantic"]
    reason: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)


class CleanupWindowOutput(RetrospectiveAgentModel):
    """Model-facing result for one program-owned target range."""

    corrected_target: str = Field(min_length=1, max_length=8_000)
    uncertain_items: list[CleanupUncertainItem] = Field(
        default_factory=list,
        max_length=40,
    )


QuestionKind = Literal[
    "technical_knowledge",
    "project_experience",
    "system_design",
    "behavioral_collaboration",
    "motivation_hr",
    "unknown",
]


class ExtractedQuestion(RetrospectiveAgentModel):
    ordinal: int = Field(ge=1)
    question_kind: QuestionKind
    origin: Literal["original", "inferred"]
    question_text: str = Field(min_length=1, max_length=4_000)
    anchor_segment_id: str = Field(default="", max_length=128)
    boundary_relation: Literal["complete", "continues_previous", "uncertain"] = (
        "complete"
    )
    question_segment_ids: list[str] = Field(default_factory=list, max_length=20)
    answer_segment_ids: list[str] = Field(default_factory=list, max_length=50)
    inference_basis: str = Field(default="", max_length=2_000)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_provenance(self) -> "ExtractedQuestion":
        if self.origin == "original" and not self.question_segment_ids:
            raise ValueError("original 问题必须包含 questionSegmentIds")
        if self.origin == "inferred" and not self.inference_basis.strip():
            raise ValueError("inferred 问题必须包含 inferenceBasis")
        if not self.answer_segment_ids:
            raise ValueError("问题必须包含 answerSegmentIds")
        expected_anchor = (
            self.question_segment_ids[0]
            if self.origin == "original"
            else self.answer_segment_ids[0]
        )
        if not self.anchor_segment_id:
            self.anchor_segment_id = expected_anchor
        if self.anchor_segment_id != expected_anchor:
            raise ValueError("问题 anchorSegmentId 必须指向首个问题或回答片段")
        return self


class QuestionExtractionOutput(RetrospectiveAgentModel):
    questions: list[ExtractedQuestion] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_order(self) -> "QuestionExtractionOutput":
        ordinals = [item.ordinal for item in self.questions]
        if ordinals != list(range(1, len(ordinals) + 1)):
            raise ValueError("问题 ordinal 必须从 1 开始连续递增")
        return self

    def validate_window(self, *, allowed_segment_ids: set[str]) -> None:
        for question in self.questions:
            evidence_ids = {
                question.anchor_segment_id,
                *question.question_segment_ids,
                *question.answer_segment_ids,
            }
            if not evidence_ids <= allowed_segment_ids:
                raise ValueError("问题引用了当前窗口之外的片段")


class QuestionExtractionModelQuestion(BaseModel):
    """Semantic fields owned by the model for one extraction window."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    question_kind: QuestionKind = "unknown"
    origin: Literal["original", "inferred"]
    question_text: str = Field(min_length=1, max_length=4_000)
    boundary_relation: Literal[
        "complete", "continues_previous", "uncertain"
    ] = "complete"
    question_segment_ids: list[str] = Field(default_factory=list, max_length=20)
    answer_segment_ids: list[str] = Field(min_length=1, max_length=50)
    inference_basis: str = Field(default="", max_length=2_000)
    confidence: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def validate_semantic_evidence(self) -> "QuestionExtractionModelQuestion":
        if self.origin == "original" and not self.question_segment_ids:
            raise ValueError("original 问题必须包含 questionSegmentIds")
        if self.origin == "inferred":
            if self.question_segment_ids:
                raise ValueError("inferred 问题不能伪造 questionSegmentIds")
            if not self.inference_basis.strip():
                raise ValueError("inferred 问题必须包含 inferenceBasis")
        return self


class QuestionExtractionModelOutput(BaseModel):
    """Small provider contract; ordering and anchors are program-owned."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    questions: list[QuestionExtractionModelQuestion] = Field(
        default_factory=list,
        max_length=200,
    )

    def materialize(
        self, *, allowed_segment_ids: set[str]
    ) -> QuestionExtractionOutput:
        questions = []
        for ordinal, candidate in enumerate(self.questions, start=1):
            anchor_segment_id = (
                candidate.question_segment_ids[0]
                if candidate.origin == "original"
                else candidate.answer_segment_ids[0]
            )
            questions.append(
                {
                    **candidate.model_dump(by_alias=True),
                    "ordinal": ordinal,
                    "anchorSegmentId": anchor_segment_id,
                }
            )
        output = QuestionExtractionOutput.model_validate({"questions": questions})
        output.validate_window(allowed_segment_ids=allowed_segment_ids)
        return output


class BoundedPoint(RetrospectiveAgentModel):
    summary: str = Field(min_length=1, max_length=1_000)
    evidence_segment_ids: list[str] = Field(default_factory=list, max_length=20)


class GapOutput(RetrospectiveAgentModel):
    kind: Literal["material", "expression", "knowledge", "experience"]
    summary: str = Field(min_length=1, max_length=1_000)
    evidence_segment_ids: list[str] = Field(default_factory=list, max_length=20)


class QuestionAnalysisOutput(RetrospectiveAgentModel):
    verdict: Literal["strong", "improvable", "high_risk", "insufficient_evidence"]
    strengths: list[BoundedPoint] = Field(default_factory=list, max_length=12)
    improvements: list[BoundedPoint] = Field(default_factory=list, max_length=12)
    omissions: list[BoundedPoint] = Field(default_factory=list, max_length=12)
    gaps: list[GapOutput] = Field(default_factory=list, max_length=12)
    evidence_level: Literal[
        "internal_evidence", "profile_conflict", "model_judgment", "insufficient"
    ]
    confidence: float = Field(ge=0, le=1)
    improvement_outline: list[str] = Field(default_factory=list, max_length=8)
    suggested_answer: str = Field(default="", max_length=6_000)


CorrectionProposalType = Literal[
    "question_text_correction",
    "question_segment_rebind",
    "speaker_correction",
    "analysis_reconsideration",
]


class RetrospectiveChatOutput(RetrospectiveAgentModel):
    result_type: Literal[
        "explanation",
        "question_text_correction",
        "question_segment_rebind",
        "speaker_correction",
        "analysis_reconsideration",
    ]
    explanation: str = Field(default="", max_length=8_000)
    question_id: str | None = Field(default=None, max_length=128)
    before: dict[str, object] = Field(default_factory=dict)
    after: dict[str, object] = Field(default_factory=dict)
    rationale: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def validate_result(self) -> "RetrospectiveChatOutput":
        if self.result_type == "explanation":
            if not self.explanation.strip():
                raise ValueError("解释结果不能为空")
            if self.before or self.after or self.question_id:
                raise ValueError("解释结果不能携带纠正字段")
            return self
        if not self.rationale.strip() or not self.after:
            raise ValueError("纠正建议必须包含修改内容和理由")
        if self.result_type != "speaker_correction" and not self.question_id:
            raise ValueError("问题纠正必须指定 questionId")
        return self
