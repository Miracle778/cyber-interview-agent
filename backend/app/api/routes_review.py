from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.agents.review_graph import build_review_graph
from app.schemas.review import ReviewQuestion, ReviewRoundSettings
from app.services.mastery import build_global_mastery_update, save_session_report
from app.services.vault import initialize_vault
from app.services.workspace import resolve_workspace

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

class ConfirmReportRequest(BaseModel):
    workspace_path: str = Field(alias="workspacePath")
    report_markdown: str = Field(alias="reportMarkdown")
    model_config = {"populate_by_name": True}

@router.post("/reports/confirm")
def confirm_report(request: ConfirmReportRequest) -> dict[str, str]:
    workspace = resolve_workspace(request.workspace_path)
    vault = initialize_vault(workspace)
    report_path = save_session_report(vault, request.report_markdown)
    mastery_markdown = build_global_mastery_update(request.report_markdown)
    mastery_path = vault / "30_mastery" / "global_mastery_review_pending.md"
    mastery_path.write_text(mastery_markdown, encoding="utf-8")
    return {"reportPath": str(report_path), "masteryPath": str(mastery_path)}
