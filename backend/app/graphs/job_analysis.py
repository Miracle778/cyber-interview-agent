from typing import Literal, TypedDict


class JobAnalysisState(TypedDict, total=False):
    job_target_id: str
    analysis_run_id: str
    stage: Literal["extracting_requirements", "mapping_profile", "mapping_projects", "finalizing", "completed"]
    pending_work_item_ids: tuple[str, ...]
    completed_work_item_ids: tuple[str, ...]
    pause_requested: bool
    terminate_requested: bool


def next_pending_work_item(state: JobAnalysisState) -> str | None:
    return next(iter(state.get("pending_work_item_ids", ())), None)
