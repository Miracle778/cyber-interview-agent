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


class CleanupOutput(RetrospectiveAgentModel):
    segments: list[CleanupSegment] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_segment_order(self) -> "CleanupOutput":
        previous_end = -1
        for segment in self.segments:
            if segment.source_start < previous_end:
                raise ValueError("片段 offset 必须有序且不重叠")
            previous_end = segment.source_end
        return self

    def validate_window(self, *, source_start: int, source_end: int) -> None:
        if source_start < 0 or source_end <= source_start:
            raise ValueError("当前文字窗口无效")
        if any(
            segment.source_start < source_start or segment.source_end > source_end
            for segment in self.segments
        ):
            raise ValueError("整理片段不属于当前文字窗口")


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
        return self


class QuestionExtractionOutput(RetrospectiveAgentModel):
    questions: list[ExtractedQuestion] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_order(self) -> "QuestionExtractionOutput":
        ordinals = [item.ordinal for item in self.questions]
        if ordinals != list(range(1, len(ordinals) + 1)):
            raise ValueError("问题 ordinal 必须从 1 开始连续递增")
        return self


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
