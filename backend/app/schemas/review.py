from typing import Literal

from pydantic import BaseModel, Field

ReviewMode = Literal["weak-point", "random-mixed", "topic-focused", "recent-mistake"]
MasteryState = Literal["unknown", "weak", "partial", "stable", "strong"]

class ReviewQuestion(BaseModel):
    id: str
    title: str
    question_text: str = Field(alias="questionText")
    reference_answer: str = Field(alias="referenceAnswer")
    topics: list[str]
    difficulty: Literal["easy", "medium", "hard"]
    key_points: list[str] = Field(alias="keyPoints")
    follow_ups: list[str] = Field(alias="followUps")
    mastery: MasteryState

    model_config = {"populate_by_name": True}

class ReviewRoundSettings(BaseModel):
    selected_topics: list[str] = Field(alias="selectedTopics")
    difficulties: list[Literal["easy", "medium", "hard"]]
    question_count: int = Field(alias="questionCount", ge=1, le=50)
    mode: ReviewMode
    allow_follow_up: bool = Field(alias="allowFollowUp", default=True)
    seed: int
    answer_model_id: str = Field(alias="answerModelId", min_length=1)
    reasoning_effort: Literal["none", "low", "medium", "high"] = Field(
        alias="reasoningEffort", default="none"
    )

    model_config = {"populate_by_name": True}
