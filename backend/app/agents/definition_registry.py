from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Literal, Mapping


AgentLifecycle = Literal["active", "deprecated", "disabled"]
ObservabilityCapability = Literal[
    "open_business",
    "cancel",
    "retry",
    "resume",
    "manual_judge",
    "export_trace",
]


class AgentRegistrationError(ValueError):
    """Stable public failure raised before an unregistered Agent persists state."""

    def __init__(self, code: str, message: str, *, graph_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.graph_id = graph_id


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Versioned control-plane definition shared by runtime and projections."""

    agent_id: str
    definition_version: str
    builder_key: str | None
    display_name: str
    route_template: str
    capabilities: frozenset[ObservabilityCapability]
    eval_pack_id: str | None
    child_components: tuple[str, ...]
    model_roles: frozenset[str] = frozenset()
    allowed_tools: frozenset[str] = frozenset()
    allowed_scopes: frozenset[str] = frozenset()
    prompt_schema_versions: tuple[tuple[str, str], ...] = ()
    input_schema_version: str = "1"
    output_schema_version: str = "1"
    context_policy_id: str = "agent-context.v1"
    retry_policy_id: str = "application-retry.v1"
    trace_policy_id: str = "trace-ledger.v3"
    system: bool = False
    run_center_visible: bool = True
    lifecycle: AgentLifecycle = "active"
    user_creatable: bool = True
    aliases: tuple[str, ...] = ()

    @property
    def graph_id(self) -> str:
        """Compatibility name used by persisted Session and Execution rows."""

        return self.agent_id

    @property
    def system_components(self) -> tuple[str, ...]:
        """Compatibility projection used by existing Run Center clients."""

        return self.child_components


class AgentDefinitionRegistry:
    """Immutable, fail-closed Agent control-plane catalog."""

    def __init__(self, definitions: Iterable[AgentDefinition]) -> None:
        items = tuple(definitions)
        by_id: dict[str, AgentDefinition] = {}
        aliases: dict[str, str] = {}
        for definition in items:
            if definition.agent_id in by_id:
                raise RuntimeError(
                    f"Agent definition contains duplicate ID: {definition.agent_id}"
                )
            if not definition.definition_version.strip():
                raise RuntimeError(
                    f"Agent definition version is empty: {definition.agent_id}"
                )
            if definition.lifecycle == "active" and not definition.builder_key:
                raise RuntimeError(
                    f"Active Agent definition has no builder: {definition.agent_id}"
                )
            by_id[definition.agent_id] = definition
            for alias in definition.aliases:
                if alias in by_id or alias in aliases:
                    raise RuntimeError(f"Agent definition alias conflicts: {alias}")
                aliases[alias] = definition.agent_id
        overlap = set(by_id) & set(aliases)
        if overlap:
            raise RuntimeError(
                "Agent definition aliases conflict with IDs: "
                + ",".join(sorted(overlap))
            )
        self._definitions = items
        self._by_id = MappingProxyType(by_id)
        self._aliases = MappingProxyType(aliases)

    @property
    def definitions(self) -> tuple[AgentDefinition, ...]:
        return self._definitions

    @property
    def by_id(self) -> Mapping[str, AgentDefinition]:
        return self._by_id

    @property
    def agent_ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    @property
    def builder_keys(self) -> frozenset[str]:
        return frozenset(
            definition.builder_key
            for definition in self._definitions
            if definition.lifecycle == "active" and definition.builder_key
        )

    def resolve(
        self,
        agent_id: str,
        *,
        include_historical: bool = False,
    ) -> AgentDefinition | None:
        canonical = self._aliases.get(agent_id, agent_id)
        definition = self._by_id.get(canonical)
        if definition is not None or not include_historical:
            return definition
        return AgentDefinition(
            agent_id=agent_id,
            definition_version="legacy",
            builder_key=None,
            display_name="历史 Agent",
            route_template="",
            capabilities=frozenset(),
            eval_pack_id=None,
            child_components=(),
            lifecycle="disabled",
            user_creatable=False,
        )

    def require(
        self,
        agent_id: str,
        *,
        for_user_creation: bool = False,
    ) -> AgentDefinition:
        if agent_id in self._aliases and for_user_creation:
            raise AgentRegistrationError(
                "agent_alias_not_creatable",
                f"历史 Agent 标识不能用于创建新任务：{agent_id}",
                graph_id=agent_id,
            )
        definition = self.resolve(agent_id)
        if definition is None:
            raise AgentRegistrationError(
                "agent_not_registered",
                f"Agent 未注册：{agent_id}",
                graph_id=agent_id,
            )
        if definition.lifecycle == "disabled":
            raise AgentRegistrationError(
                "agent_disabled",
                f"Agent 已停用：{agent_id}",
                graph_id=agent_id,
            )
        if definition.lifecycle == "deprecated" and for_user_creation:
            raise AgentRegistrationError(
                "agent_deprecated",
                f"Agent 已弃用，不能创建新任务：{agent_id}",
                graph_id=agent_id,
            )
        if for_user_creation and not definition.user_creatable:
            raise AgentRegistrationError(
                "agent_not_user_creatable",
                f"该 Agent 只能由系统内部创建：{agent_id}",
                graph_id=agent_id,
            )
        return definition

    def validate_builder_catalog(self, builder_keys: set[str] | frozenset[str]) -> None:
        expected = set(self.builder_keys)
        actual = set(builder_keys)
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        if not missing and not unknown:
            return
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        raise RuntimeError("Agent builder catalog mismatch: " + "; ".join(details))


def _definition(
    agent_id: str,
    builder_key: str,
    display_name: str,
    route_template: str,
    *capabilities: ObservabilityCapability,
    eval_pack_id: str | None = None,
    child_components: tuple[str, ...] = (),
    model_roles: tuple[str, ...] = (),
    allowed_tools: tuple[str, ...] = (),
    allowed_scopes: tuple[str, ...] = (),
    prompt_schema_versions: tuple[tuple[str, str], ...] = (),
    input_schema_version: str = "1",
    output_schema_version: str = "1",
    context_policy_id: str = "agent-context.v1",
    retry_policy_id: str = "application-retry.v1",
    trace_policy_id: str = "trace-ledger.v3",
    system: bool = False,
    run_center_visible: bool = True,
    lifecycle: AgentLifecycle = "active",
    user_creatable: bool | None = None,
    aliases: tuple[str, ...] = (),
) -> AgentDefinition:
    return AgentDefinition(
        agent_id=agent_id,
        definition_version="1",
        builder_key=builder_key,
        display_name=display_name,
        route_template=route_template,
        capabilities=frozenset(capabilities),
        eval_pack_id=eval_pack_id,
        child_components=child_components,
        model_roles=frozenset(model_roles),
        allowed_tools=frozenset(allowed_tools),
        allowed_scopes=frozenset(allowed_scopes),
        prompt_schema_versions=tuple(sorted(prompt_schema_versions)),
        input_schema_version=input_schema_version,
        output_schema_version=output_schema_version,
        context_policy_id=context_policy_id,
        retry_policy_id=retry_policy_id,
        trace_policy_id=trace_policy_id,
        system=system,
        run_center_visible=run_center_visible,
        lifecycle=lifecycle,
        user_creatable=(not system if user_creatable is None else user_creatable),
        aliases=aliases,
    )


_DEFINITIONS = (
    _definition(
        "question.curate",
        "question_curation_graph",
        "题库整理",
        "/review",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="question-curation.v2",
        child_components=(
            "question_discovery",
            "question_enrichment",
            "question_revision",
            "curation_command_classifier",
            "curation_context_summarizer",
            "curation_command_responder",
            "context_summarization",
        ),
        model_roles=("question_generation", "report_summarization"),
    ),
    _definition(
        "question.revise",
        "question_curation_graph",
        "题目重写",
        "/review",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="question-revision.v2",
        child_components=(
            "question_discovery",
            "question_enrichment",
            "question_revision",
            "context_summarization",
        ),
        model_roles=("question_generation", "report_summarization"),
    ),
    _definition(
        "review.round",
        "review_round_graph",
        "复习助手",
        "/review",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="review-round.v2",
        child_components=(
            "review_round_evaluator",
            "review_round_reporter",
            "review_discussion",
            "project_answer_evaluator",
            "review_turn_classifier",
            "context_summarization",
        ),
        model_roles=("answer_evaluation", "agent_chat", "report_summarization"),
    ),
    _definition(
        "review.discussion",
        "review_round_graph",
        "深入讨论",
        "/review",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="review-discussion.v2",
        child_components=(
            "review_round_evaluator",
            "review_round_reporter",
            "review_discussion",
            "project_answer_evaluator",
            "review_turn_classifier",
            "context_summarization",
        ),
        model_roles=("answer_evaluation", "agent_chat", "report_summarization"),
    ),
    _definition(
        "review.single",
        "single_review_graph",
        "单题复习",
        "/review",
        "open_business",
        "cancel",
        "retry",
        "manual_judge",
        "export_trace",
        eval_pack_id="review-single.v2",
        child_components=(
            "single_review_evaluator",
            "single_review_reporter",
            "context_summarization",
        ),
        model_roles=("answer_evaluation", "report_summarization"),
    ),
    _definition(
        "profile.manage",
        "profile_graph",
        "画像助手",
        "/profile/assistant",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="profile-assistant.v2",
        child_components=(
            "profile_extraction",
            "profile_assessment",
            "profile_chat",
            "profile_action_planner",
            "profile_conversation_proposal",
            "context_summarization",
        ),
        model_roles=(
            "profile_extraction",
            "profile_assessment",
            "agent_chat",
            "report_summarization",
        ),
        allowed_tools=(
            "list_personal_materials",
            "search_personal_materials",
            "read_personal_evidence",
            "read_personal_evidence_batch",
            "get_profile_claims",
            "get_profile_claim_evidence",
            "compare_material_versions",
            "search_active_knowledge",
            "get_profile_publication_status",
        ),
        allowed_scopes=("profile.materials", "knowledge.active"),
    ),
    _definition(
        "job.analysis",
        "job_target_agents",
        "岗位分析",
        "/targets",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="job-requirement-analysis.v2",
        child_components=(
            "job_analysis",
            "project_deep_dive",
            "project_question_generation",
            "context_summarization",
        ),
        model_roles=("job_analysis", "project_deep_dive", "report_summarization"),
    ),
    _definition(
        "project.deep_dive",
        "job_target_agents",
        "项目深挖",
        "/targets",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        eval_pack_id="project-deep-dive-coaching.v2",
        child_components=(
            "job_analysis",
            "project_deep_dive",
            "project_question_generation",
            "context_summarization",
        ),
        model_roles=("job_analysis", "project_deep_dive", "report_summarization"),
    ),
    _definition(
        "interview.retrospective",
        "interview_retrospective_agents",
        "面试复盘",
        "/retrospectives",
        "open_business",
        "cancel",
        "retry",
        "resume",
        "manual_judge",
        "export_trace",
        child_components=(
            "interview_retrospective_cleanup",
            "interview_retrospective_question_extraction",
            "interview_retrospective_question_analysis",
            "interview_retrospective_chat",
            "interview_retrospective_history_search_plan",
            "interview_retrospective_history_batch_summary",
            "interview_retrospective_history_summary",
            "interview_retrospective_history_report",
            "context_summarization",
        ),
        model_roles=(
            "retrospective_analysis",
            "retrospective_chat",
            "report_summarization",
        ),
        allowed_tools=(
            "read_retrospective_summary",
            "read_question_analysis",
            "read_source_excerpt",
            "search_target_requirements",
            "search_confirmed_profile",
            "search_review_questions",
            "search_active_knowledge",
        ),
        allowed_scopes=("interview_retrospective.read",),
        aliases=(
            "interview.retrospective.analysis",
            "interview.retrospective.chat",
            "interview.retrospective.history",
        ),
    ),
    _definition(
        "profile.ingest",
        "profile_graph",
        "简历画像整理",
        "",
        "export_trace",
        eval_pack_id="profile-ingest.v2",
        child_components=(
            "profile_extraction",
            "profile_assessment",
            "profile_chat",
            "profile_action_planner",
            "profile_conversation_proposal",
            "context_summarization",
        ),
        model_roles=(
            "profile_extraction",
            "profile_assessment",
            "agent_chat",
            "report_summarization",
        ),
        allowed_tools=(
            "list_personal_materials",
            "search_personal_materials",
            "read_personal_evidence",
            "read_personal_evidence_batch",
            "get_profile_claims",
            "get_profile_claim_evidence",
            "compare_material_versions",
            "search_active_knowledge",
            "get_profile_publication_status",
        ),
        allowed_scopes=("profile.materials", "knowledge.active"),
        system=True,
    ),
    _definition(
        "profile.assess",
        "profile_graph",
        "画像评估",
        "",
        "export_trace",
        eval_pack_id="profile-assessment.v2",
        child_components=(
            "profile_extraction",
            "profile_assessment",
            "profile_chat",
            "profile_action_planner",
            "profile_conversation_proposal",
            "context_summarization",
        ),
        model_roles=(
            "profile_extraction",
            "profile_assessment",
            "agent_chat",
            "report_summarization",
        ),
        allowed_tools=(
            "list_personal_materials",
            "search_personal_materials",
            "read_personal_evidence",
            "read_personal_evidence_batch",
            "get_profile_claims",
            "get_profile_claim_evidence",
            "compare_material_versions",
            "search_active_knowledge",
            "get_profile_publication_status",
        ),
        allowed_scopes=("profile.materials", "knowledge.active"),
        system=True,
    ),
    _definition(
        "quality.evaluate",
        "quality_evaluation_agents",
        "运行质量评估",
        "",
        "export_trace",
        child_components=(
            "quality_evaluation_judge",
            "quality_evaluation_judge_v2",
            "quality_evaluation_pairwise_judge_v2",
        ),
        model_roles=("answer_evaluation",),
        system=True,
        run_center_visible=False,
    ),
    _definition(
        "knowledge.publish",
        "publication_graph",
        "知识发布",
        "",
        "export_trace",
        system=True,
        run_center_visible=False,
    ),
    _definition(
        "diagnostic.echo",
        "diagnostic_echo_graph",
        "诊断回声",
        "",
        system=True,
        run_center_visible=False,
    ),
    _definition(
        "diagnostic.approval",
        "diagnostic_approval_graph",
        "诊断确认",
        "",
        system=True,
        run_center_visible=False,
    ),
    _definition(
        "diagnostic.security",
        "diagnostic_security_graph",
        "诊断安全",
        "",
        system=True,
        run_center_visible=False,
    ),
)


AGENT_DEFINITION_REGISTRY = AgentDefinitionRegistry(_DEFINITIONS)
AGENT_DEFINITIONS = AGENT_DEFINITION_REGISTRY.by_id


def resolve_agent_definition(
    agent_id: str,
    *,
    include_historical: bool = False,
) -> AgentDefinition | None:
    return AGENT_DEFINITION_REGISTRY.resolve(
        agent_id,
        include_historical=include_historical,
    )


def require_agent_definition(
    agent_id: str,
    *,
    for_user_creation: bool = False,
) -> AgentDefinition:
    return AGENT_DEFINITION_REGISTRY.require(
        agent_id,
        for_user_creation=for_user_creation,
    )
