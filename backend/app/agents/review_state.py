from typing import Literal, TypedDict

from app.schemas.review import ReviewQuestion, ReviewRoundSettings

class AnswerEvaluation(TypedDict):
    question_id: str
    score: Literal["poor", "partial", "good"]
    missing_key_points: list[str]
    evidence: str

class ReviewState(TypedDict, total=False):
    settings: ReviewRoundSettings
    questions: list[ReviewQuestion]
    current_question: ReviewQuestion
    user_answer: str
    evaluation: AnswerEvaluation
    report_markdown: str
