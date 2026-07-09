from app.agents.review_state import AnswerEvaluation
from app.schemas.review import ReviewQuestion, ReviewRoundSettings

MASTERY_RANK = {"weak": 0, "partial": 1, "unknown": 2, "stable": 3, "strong": 4}

def select_next_question(questions: list[ReviewQuestion], settings: ReviewRoundSettings) -> ReviewQuestion:
    scoped = [
        question for question in questions
        if not settings.selected_topics or any(topic in settings.selected_topics for topic in question.topics)
    ]
    if not scoped:
        raise ValueError("没有可用题目")
    return sorted(scoped, key=lambda question: MASTERY_RANK[question.mastery])[0]

def evaluate_answer(question: ReviewQuestion, answer: str) -> AnswerEvaluation:
    missing = [point for point in question.key_points if point.lower() not in answer.lower()]
    if not missing:
        score = "good"
    elif len(missing) < len(question.key_points):
        score = "partial"
    else:
        score = "poor"
    return {
        "question_id": question.id,
        "score": score,
        "missing_key_points": missing,
        "evidence": answer,
    }
