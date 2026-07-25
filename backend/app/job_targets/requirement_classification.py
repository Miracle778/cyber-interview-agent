from __future__ import annotations

import re


_HEADING = re.compile(
    r"^(?:公司简介|岗位介绍|职位介绍|团队介绍|部门介绍|任职资格|职位要求|岗位要求|优先(?:考虑)?条件|加分项|岗位职责|工作职责|福利待遇|工作地点)[:：]?$"
)
_BACKGROUND_LABEL = re.compile(r"^(?:公司|部门|团队|技术团队|业务线|产品线|事业群)[：:].+$")
_BACKGROUND_NAME = re.compile(r"^.{1,20}(?:团队|部门|事业群|业务线|产品线)$")
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
    "需要",
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
    "团队负责",
    "部门负责",
    "团队介绍",
    "部门介绍",
    "公司简介",
    "业务线",
    "产品线",
    "福利",
    "工作地点",
)


def is_job_background_or_heading(text: str) -> bool:
    """Keep company/team narration and section labels out of the confirmable queue."""
    normalized = re.sub(r"\s+", "", text).strip("-:：；;。")
    if not normalized:
        return True
    if _HEADING.fullmatch(normalized):
        return True
    if _BACKGROUND_LABEL.fullmatch(normalized):
        return True
    if re.match(r"^(?:团队|部门|技术团队).{0,18}(?:是|为|负责|服务|致力于)", normalized):
        return True
    has_candidate_cue = any(cue in normalized for cue in _CANDIDATE_CUES)
    has_background_cue = any(cue in normalized for cue in _BACKGROUND_CUES)
    if _BACKGROUND_NAME.fullmatch(normalized) and not has_candidate_cue:
        return True
    return has_background_cue and not has_candidate_cue
