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
            segment.source_start < source_start
            or segment.source_end > source_end
            for segment in self.segments
        ):
            raise ValueError("整理片段不属于当前文字窗口")
