from typing import Literal, TypedDict


class ProjectDeepDiveState(TypedDict, total=False):
    job_target_id: str
    project_claim_id: str
    session_id: str
    execution_id: str
    current_stage: Literal["background", "role", "solution", "difficulty", "outcome", "tradeoff", "target_follow_up", "finished"]
    current_question_id: str
    completed_stage_ids: tuple[str, ...]
    follow_up_ids: tuple[str, ...]
    waiting_for_input: bool
    pause_requested: bool
    end_requested: bool


STAGES = ("background", "role", "solution", "difficulty", "outcome", "tradeoff", "target_follow_up", "finished")


def advance_stage(stage: str) -> str:
    index = STAGES.index(stage)
    return STAGES[min(index + 1, len(STAGES) - 1)]
