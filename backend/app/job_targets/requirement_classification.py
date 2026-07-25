from __future__ import annotations

import re


_HEADING = re.compile(
    r"^(?:任职资格|职位要求|岗位要求|优先(?:考虑)?条件|加分项|岗位职责|工作职责)[:：]?$"
)
_CANDIDATE_CUES = (
    "要求",
    "具备",
    "熟悉",
    "掌握",
    "精通",
    "了解",
    "学历",
    "经验",
    "能力",
    "优先",
    "负责",
    "主导",
    "参与",
    "能够",
)
_BACKGROUND_CUES = (
    "团队是",
    "团队为",
    "服务于",
    "致力于",
    "产品包括",
    "产品有",
    "全站",
    "最大的",
    "上线了",
    "对外输出",
    "技术团队",
    "基础中间件",
)


def is_job_background_or_heading(text: str) -> bool:
    """Keep company/team narration and section labels out of the confirmable queue."""
    normalized = re.sub(r"\s+", "", text).strip("-:：；;。")
    if not normalized:
        return True
    if _HEADING.fullmatch(normalized):
        return True
    has_candidate_cue = any(cue in normalized for cue in _CANDIDATE_CUES)
    has_background_cue = any(cue in normalized for cue in _BACKGROUND_CUES)
    return has_background_cue and not has_candidate_cue
