JOB_ANALYSIS_PROMPT_VERSION = "job-analysis-v1"
PROJECT_DEEP_DIVE_PROMPT_VERSION = "project-deep-dive-v1"


def render_job_analysis_input(*, role: str, seniority: str, document: str) -> str:
    return f"岗位：{role}\n职级：{seniority}\n岗位材料：\n{document}"


def render_deep_dive_turn(*, stage: str, project: dict, answer: str) -> str:
    return f"阶段：{stage}\n已确认项目：{project}\n候选人回答：{answer}"
