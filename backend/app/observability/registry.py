from __future__ import annotations

from dataclasses import dataclass

from app.observability.models import ObservabilityCapability


@dataclass(frozen=True, slots=True)
class AgentObservabilityRegistration:
    graph_id: str
    display_name: str
    route_template: str
    capabilities: frozenset[ObservabilityCapability]
    eval_pack_id: str | None
    system_components: tuple[str, ...]
    system: bool = False


def _registration(
    graph_id: str,
    display_name: str,
    route_template: str,
    *capabilities: ObservabilityCapability,
    eval_pack_id: str | None = None,
    system_components: tuple[str, ...] = (),
    system: bool = False,
) -> AgentObservabilityRegistration:
    return AgentObservabilityRegistration(
        graph_id=graph_id,
        display_name=display_name,
        route_template=route_template,
        capabilities=frozenset(capabilities),
        eval_pack_id=eval_pack_id,
        system_components=system_components,
        system=system,
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
        eval_pack_id="question-curation.v1",
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
        eval_pack_id="question-curation.v1",
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
        eval_pack_id="review.v1",
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
        eval_pack_id="review.v1",
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
        eval_pack_id="review.v1",
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
        eval_pack_id="profile.v1",
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
        eval_pack_id="job-analysis.v1",
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
        eval_pack_id="project-deep-dive.v1",
        system_components=("project_deep_dive",),
    ),
    _registration(
        "profile.ingest",
        "简历画像整理",
        "",
        "export_trace",
        eval_pack_id="profile.v1",
        system_components=("profile_extraction",),
        system=True,
    ),
    _registration(
        "profile.assess",
        "画像评估",
        "",
        "export_trace",
        eval_pack_id="profile.v1",
        system_components=("profile_assessment",),
        system=True,
    ),
    _registration(
        "knowledge.publish",
        "知识发布",
        "",
        "export_trace",
        system=True,
    ),
    _registration("diagnostic.echo", "诊断回声", "", system=True),
    _registration("diagnostic.approval", "诊断确认", "", system=True),
    _registration("diagnostic.security", "诊断安全", "", system=True),
)


AGENT_OBSERVABILITY_REGISTRY = {
    registration.graph_id: registration for registration in _REGISTRATIONS
}

if len(AGENT_OBSERVABILITY_REGISTRY) != len(_REGISTRATIONS):
    raise RuntimeError("Agent observability registry contains duplicate graph IDs")


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
