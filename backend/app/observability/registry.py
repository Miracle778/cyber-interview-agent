from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.observability.models import ObservabilityCapability


AgentLifecycle = Literal["active", "deprecated", "disabled"]


class AgentRegistrationError(ValueError):
    """Stable public failure raised before an unregistered Agent can persist state."""

    def __init__(self, code: str, message: str, *, graph_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.graph_id = graph_id


@dataclass(frozen=True, slots=True)
class AgentObservabilityRegistration:
    graph_id: str
    display_name: str
    route_template: str
    capabilities: frozenset[ObservabilityCapability]
    eval_pack_id: str | None
    system_components: tuple[str, ...]
    system: bool = False
    run_center_visible: bool = True
    lifecycle: AgentLifecycle = "active"
    user_creatable: bool = True


def _registration(
    graph_id: str,
    display_name: str,
    route_template: str,
    *capabilities: ObservabilityCapability,
    eval_pack_id: str | None = None,
    system_components: tuple[str, ...] = (),
    system: bool = False,
    run_center_visible: bool = True,
    lifecycle: AgentLifecycle = "active",
    user_creatable: bool | None = None,
) -> AgentObservabilityRegistration:
    return AgentObservabilityRegistration(
        graph_id=graph_id,
        display_name=display_name,
        route_template=route_template,
        capabilities=frozenset(capabilities),
        eval_pack_id=eval_pack_id,
        system_components=system_components,
        system=system,
        run_center_visible=run_center_visible,
        lifecycle=lifecycle,
        user_creatable=(not system if user_creatable is None else user_creatable),
    )


_REGISTRATIONS = (
    _registration(
        "question.curate",
        "题库整理",
        "/review",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="question-curation.v2",
        system_components=("question_generation", "report_summarization"),
    ),
    _registration(
        "question.revise",
        "题目重写",
        "/review",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="question-revision.v2",
        system_components=("question_generation", "report_summarization"),
    ),
    _registration(
        "review.round",
        "复习助手",
        "/review",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="review-round.v2",
        system_components=("answer_evaluation", "agent_chat", "report_summarization"),
    ),
    _registration(
        "review.discussion",
        "深入讨论",
        "/review",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="review-discussion.v2",
        system_components=("agent_chat", "report_summarization"),
    ),
    _registration(
        "review.single",
        "单题复习",
        "/review",
        "open_business",
        "cancel",
        "retry",
        "manual_judge",
        "export_trace",
        eval_pack_id="review-single.v2",
        system_components=("answer_evaluation", "report_summarization"),
    ),
    _registration(
        "profile.manage",
        "画像助手",
        "/profile/assistant",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="profile-assistant.v2",
        system_components=("agent_chat", "profile_assessment"),
    ),
    _registration(
        "job.analysis",
        "岗位分析",
        "/targets",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="job-requirement-analysis.v2",
        system_components=("job_analysis",),
    ),
    _registration(
        "project.deep_dive",
        "项目深挖",
        "/targets",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="project-deep-dive-coaching.v2",
        system_components=("project_deep_dive",),
    ),
    _registration(
        "interview.retrospective",
        "面试复盘",
        "/retrospectives",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        system_components=("retrospective_analysis",),
    ),
    _registration(
        "profile.ingest",
        "简历画像整理",
        "",
        "export_trace",
        eval_pack_id="profile-ingest.v2",
        system_components=("profile_extraction",),
        system=True,
    ),
    _registration(
        "profile.assess",
        "画像评估",
        "",
        "export_trace",
        eval_pack_id="profile-assessment.v2",
        system_components=("profile_assessment",),
        system=True,
    ),
    _registration(
        "knowledge.publish",
        "知识发布",
        "",
        "export_trace",
        system=True,
        run_center_visible=False,
    ),
    _registration(
        "diagnostic.echo",
        "诊断回声",
        "",
        system=True,
        run_center_visible=False,
    ),
    _registration(
        "diagnostic.approval",
        "诊断确认",
        "",
        system=True,
        run_center_visible=False,
    ),
    _registration(
        "diagnostic.security",
        "诊断安全",
        "",
        system=True,
        run_center_visible=False,
    ),
)


AGENT_OBSERVABILITY_REGISTRY = {
    registration.graph_id: registration for registration in _REGISTRATIONS
}

_LEGACY_GRAPH_ID_ALIASES = {
    "interview.retrospective.analysis": "interview.retrospective",
    "interview.retrospective.chat": "interview.retrospective",
    "interview.retrospective.history": "interview.retrospective",
}

if len(AGENT_OBSERVABILITY_REGISTRY) != len(_REGISTRATIONS):
    raise RuntimeError("Agent observability registry contains duplicate graph IDs")


def resolve_observability_registration(
    graph_id: str,
    *,
    include_historical: bool = False,
) -> AgentObservabilityRegistration | None:
    canonical = _LEGACY_GRAPH_ID_ALIASES.get(graph_id, graph_id)
    registration = AGENT_OBSERVABILITY_REGISTRY.get(canonical)
    if registration is not None or not include_historical:
        return registration
    return AgentObservabilityRegistration(
        graph_id=graph_id,
        display_name="历史 Agent",
        route_template="",
        capabilities=frozenset(),
        eval_pack_id=None,
        system_components=(),
        system=False,
        run_center_visible=True,
        lifecycle="disabled",
        user_creatable=False,
    )


def require_registration(
    graph_id: str,
    *,
    for_user_creation: bool = False,
) -> AgentObservabilityRegistration:
    if graph_id in _LEGACY_GRAPH_ID_ALIASES and for_user_creation:
        raise AgentRegistrationError(
            "agent_alias_not_creatable",
            f"历史 Agent 标识不能用于创建新任务：{graph_id}",
            graph_id=graph_id,
        )
    registration = resolve_observability_registration(graph_id)
    if registration is None:
        raise AgentRegistrationError(
            "agent_not_registered",
            f"Agent 未注册：{graph_id}",
            graph_id=graph_id,
        )
    if registration.lifecycle == "disabled":
        raise AgentRegistrationError(
            "agent_disabled",
            f"Agent 已停用：{graph_id}",
            graph_id=graph_id,
        )
    if registration.lifecycle == "deprecated" and for_user_creation:
        raise AgentRegistrationError(
            "agent_deprecated",
            f"Agent 已弃用，不能创建新任务：{graph_id}",
            graph_id=graph_id,
        )
    if for_user_creation and not registration.user_creatable:
        raise AgentRegistrationError(
            "agent_not_user_creatable",
            f"该 Agent 只能由系统内部创建：{graph_id}",
            graph_id=graph_id,
        )
    return registration


def assert_registry_complete(graph_ids: frozenset[str] | set[str]) -> None:
    expected = set(AGENT_OBSERVABILITY_REGISTRY)
    actual = set(graph_ids)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        raise RuntimeError(
            "Agent observability registry mismatch: " + "; ".join(details)
        )
