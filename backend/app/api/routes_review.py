from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.agents.review_graph import build_review_graph
from app.schemas.review import ReviewQuestion, ReviewRoundSettings

router = APIRouter(prefix="/api/review", tags=["review"])

class ReviewRunRequest(BaseModel):
    questions: list[ReviewQuestion]
    settings: ReviewRoundSettings
    user_answer: str = Field(alias="userAnswer")
    model_config = {"populate_by_name": True}

@router.post("/run")
def run_review(request: ReviewRunRequest) -> dict:
    graph = build_review_graph()
    return graph.invoke({
        "questions": request.questions,
        "settings": request.settings,
        "user_answer": request.user_answer,
    })
