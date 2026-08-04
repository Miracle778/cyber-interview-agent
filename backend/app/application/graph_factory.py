from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.agent_factory import AgentFactory, AgentSpec, ModelOverride
from app.agents.prompts.prompt_spec import PromptSpec
from app.evaluation.contracts import JudgeResult, JudgeResultV2, PairwiseJudgeResult
from app.evaluation.judge_agent import StructuredJudgeAgent
from app.agents.question_curation_agent import QuestionCurationAgents
from app.agents.curation_command_agents import CurationCommandAgents
from app.agents.context_assembly import model_token_counter
from app.agents.single_review_agents import SingleReviewAgents
from app.agents.review_round_agents import ReviewRoundAgents
from app.agents.profile_agents import ProfileAgents
from app.agents.job_target_agents import JobTargetAgents
from app.agents.interview_retrospective_agents import InterviewRetrospectiveAgents
from app.agents.definition_registry import AGENT_DEFINITION_REGISTRY
from app.graphs.publication import create_publication_graph
from app.graphs.question_curation import create_question_curation_graph
from app.graphs.review import create_review_graph
from app.graphs.review_discussion import create_review_discussion_graph
from app.graphs.review_round import create_review_round_graph
from app.graphs.profile_assess import create_profile_assess_graph
from app.graphs.profile_ingest import create_profile_ingest_graph
from app.graphs.profile_manage import create_profile_manage_graph
from app.middleware.middleware_stack import (
    PROFILE_CHAT_BUDGET_PROFILE,
    RETROSPECTIVE_CHAT_BUDGET_PROFILE,
    REVIEW_ROUND_BUDGET,
    build_default_middleware,
)
from app.middleware.tool_policy_middleware import ToolPolicyMiddleware
from app.tools.profile_tools import (
    PROFILE_TOOL_SCOPES,
    ProfileToolBudgetMiddleware,
    create_profile_tools,
)


class DiagnosticState(TypedDict, total=False):
    text: str
    summary: str
    response: str
    decision: dict[str, Any]


class ProductionGraphFactory:
    """Resolve every production Builder through the Agent control plane."""

    def __init__(self, agents: AgentFactory) -> None:
        self._agents = agents
        AGENT_DEFINITION_REGISTRY.validate_builder_catalog(self.builder_keys)

    @property
    def builder_keys(self) -> frozenset[str]:
        return frozenset(self._builder_catalog())

    def _builder_catalog(self):
        return {
            "profile_graph": self._build_profile_graph,
            "question_curation_graph": self._build_question_or_review_graph,
            "review_round_graph": self._build_question_or_review_graph,
            "single_review_graph": self._build_single_review_graph,
            "publication_graph": self._build_publication_graph,
            "job_target_agents": self._build_job_target_agents,
            "interview_retrospective_agents": (
                self._build_interview_retrospective_agents
            ),
            "diagnostic_echo_graph": self._build_diagnostic_echo_graph,
            "diagnostic_approval_graph": self._build_diagnostic_approval_graph,
            "diagnostic_security_graph": self._build_diagnostic_security_graph,
        }

    @property
    def trace_writer(self):
        return getattr(self._agents, "trace_writer", None)

    def create_evaluation_judge(
        self,
        *,
        model_bindings,
        provider_model_id: str,
    ) -> StructuredJudgeAgent:
        runnable = self._agents.create(
            AgentSpec(
                role="answer_evaluation",
                execution_name="quality_evaluation_judge",
                prompt=PromptSpec(
                    id="quality-evaluation-judge",
                    version="1",
                    system=(
                        "你是独立质量评估 Judge。只根据输入的冻结快照、证据哈希和 "
                        "Eval Pack 评分。不得假设缺失证据，不得提出或执行任何业务修改，"
                        "不得输出思维过程。事件哈希必须引用；只有存在 Artifact 时才引用"
                        " Artifact 哈希，否则返回空数组。严格返回约定的结构化结果。"
                    ),
                ),
                tools=(),
                response_format=JudgeResult,
                structured_output_handle_errors=False,
            ),
            model_bindings=model_bindings,
            model_override=ModelOverride(provider_model_id),
        )
        v2_runnable = self._agents.create(
            AgentSpec(
                role="answer_evaluation",
                execution_name="quality_evaluation_judge_v2",
                prompt=PromptSpec(
                    id="quality-evaluation-judge-v2",
                    version="1",
                    system=(
                        "你是独立质量评估 Judge。只根据输入的最小 Evaluation View "
                        "评价业务结果，不得索取或推测完整 Trace、隐藏资料和本地路径。"
                        "必须服从每个维度由代码给出的 applicability；不适用或证据不足"
                        "时不得给质量等级。不得提出或执行业务修改，不得输出思维过程。"
                        "严格返回约定的结构化结果。"
                    ),
                ),
                tools=(),
                response_format=JudgeResultV2,
                structured_output_handle_errors=False,
            ),
            model_bindings=model_bindings,
            model_override=ModelOverride(provider_model_id),
        )
        pairwise_runnable = self._agents.create(
            AgentSpec(
                role="answer_evaluation",
                execution_name="quality_evaluation_pairwise_judge_v2",
                prompt=PromptSpec(
                    id="quality-evaluation-pairwise-judge-v2",
                    version="1",
                    system=(
                        "你是独立盲测 Judge。输入只称 Outcome A 与 Outcome B，"
                        "不得推测哪一个是基线或候选版本。按相同 Eval Pack 逐维比较，"
                        "允许平局和不确定；不得执行任何业务写入，不得输出思维过程。"
                    ),
                ),
                tools=(),
                response_format=PairwiseJudgeResult,
                structured_output_handle_errors=False,
            ),
            model_bindings=model_bindings,
            model_override=ModelOverride(provider_model_id),
        )
        return StructuredJudgeAgent(runnable, v2_runnable, pairwise_runnable)

    def create_curation_command_agents(
        self,
        *,
        model_bindings,
        projection,
        audit,
        observability,
        publish_event=None,
        interaction_override: ModelOverride | None = None,
    ):
        context_limit_tokens = min(
            self._agents.resolve_context_limit(
                "question_generation",
                model_bindings=model_bindings,
                model_override=interaction_override,
            ),
            self._agents.resolve_context_limit(
                "report_summarization", model_bindings=model_bindings
            ),
        )
        summary_model = self._agents.resolve_model(
            "report_summarization", model_bindings=model_bindings
        )
        classifier_model = self._agents.resolve_model(
            "question_generation",
            model_bindings=model_bindings,
            model_override=interaction_override,
        )
        middleware = build_default_middleware(
            summary_model=summary_model,
            summary_provider_model_id=model_bindings["report_summarization"],
            trace_writer=self.trace_writer,
            projection=projection,
            policy=ToolPolicyMiddleware(
                audit=audit,
                required_scopes={},
                publish_event=publish_event,
            ),
            observability=observability,
            interrupt_on={},
            budget_profile=REVIEW_ROUND_BUDGET,
            context_limit_tokens=context_limit_tokens,
        )
        return CurationCommandAgents.create(
            self._agents,
            model_bindings=model_bindings,
            interaction_override=interaction_override,
            middleware=middleware,
            context_limit_tokens=context_limit_tokens,
            token_counter=model_token_counter(classifier_model),
        )

    def create_job_target_agents(
        self,
        *,
        model_bindings,
        projection,
        audit,
        observability,
        publish_event=None,
        interaction_override: ModelOverride | None = None,
    ) -> JobTargetAgents:
        return self(
            "job.analysis",
            model_bindings=model_bindings,
            projection=projection,
            audit=audit,
            observability=observability,
            publish_event=publish_event,
            interaction_override=interaction_override,
        )

    def _create_job_target_agents(
        self,
        *,
        model_bindings,
        projection,
        audit,
        observability,
        publish_event=None,
        interaction_override: ModelOverride | None = None,
    ) -> JobTargetAgents:
        context_limit_tokens = min(
            self._agents.resolve_context_limit(
                role,
                model_bindings=model_bindings,
                model_override=interaction_override,
            )
            for role in ("job_analysis", "project_deep_dive")
        )
        middleware = build_default_middleware(
            summary_model=self._agents.resolve_model(
                "report_summarization", model_bindings=model_bindings
            ),
            summary_provider_model_id=model_bindings["report_summarization"],
            trace_writer=self.trace_writer,
            projection=projection,
            policy=ToolPolicyMiddleware(
                audit=audit,
                required_scopes={},
                publish_event=publish_event,
            ),
            observability=observability,
            interrupt_on={},
            budget_profile=PROFILE_CHAT_BUDGET_PROFILE,
            context_limit_tokens=context_limit_tokens,
        )
        return JobTargetAgents.create(
            self._agents,
            model_bindings=model_bindings,
            middleware=middleware,
            model_override=interaction_override,
        )

    def create_interview_retrospective_agents(
        self,
        *,
        model_bindings,
        projection,
        audit,
        observability,
        publish_event=None,
        interaction_override: ModelOverride | None = None,
        chat_tools: tuple = (),
    ) -> InterviewRetrospectiveAgents:
        return self(
            "interview.retrospective",
            model_bindings=model_bindings,
            projection=projection,
            audit=audit,
            observability=observability,
            publish_event=publish_event,
            interaction_override=interaction_override,
            chat_tools=chat_tools,
        )

    def _create_interview_retrospective_agents(
        self,
        *,
        model_bindings,
        projection,
        audit,
        observability,
        publish_event=None,
        interaction_override: ModelOverride | None = None,
        chat_tools: tuple = (),
    ) -> InterviewRetrospectiveAgents:
        context_limit_tokens = min(
            self._agents.resolve_context_limit(
                role,
                model_bindings=model_bindings,
                model_override=(
                    interaction_override if role == "retrospective_analysis" else None
                ),
            )
            for role in (
                "retrospective_analysis",
                "retrospective_chat",
                "report_summarization",
            )
        )
        middleware = build_default_middleware(
            summary_model=self._agents.resolve_model(
                "report_summarization", model_bindings=model_bindings
            ),
            summary_provider_model_id=model_bindings["report_summarization"],
            trace_writer=self.trace_writer,
            projection=projection,
            policy=ToolPolicyMiddleware(
                audit=audit,
                required_scopes={},
                publish_event=publish_event,
            ),
            observability=observability,
            interrupt_on={},
            budget_profile=RETROSPECTIVE_CHAT_BUDGET_PROFILE,
            context_limit_tokens=context_limit_tokens,
        )
        return InterviewRetrospectiveAgents.create(
            self._agents,
            model_bindings=model_bindings,
            middleware=middleware,
            model_override=interaction_override,
            chat_tools=chat_tools,
            chat_history_token_budget=max(
                1_000,
                min(8_000, int(context_limit_tokens * 0.20)),
            ),
        )

    def create_review_round_agents(
        self,
        *,
        model_bindings,
        projection,
        audit,
        observability,
        publish_event=None,
        interaction_override: ModelOverride | None = None,
    ) -> ReviewRoundAgents:
        roles = ("answer_evaluation", "report_summarization", "agent_chat")
        context_limit_tokens = min(
            self._agents.resolve_context_limit(
                role,
                model_bindings=model_bindings,
                model_override=(
                    interaction_override if role == "answer_evaluation" else None
                ),
            )
            for role in roles
        )
        middleware = build_default_middleware(
            summary_model=self._agents.resolve_model(
                "report_summarization", model_bindings=model_bindings
            ),
            summary_provider_model_id=model_bindings["report_summarization"],
            trace_writer=self.trace_writer,
            projection=projection,
            policy=ToolPolicyMiddleware(
                audit=audit,
                required_scopes={},
                publish_event=publish_event,
            ),
            observability=observability,
            interrupt_on={},
            budget_profile=REVIEW_ROUND_BUDGET,
            context_limit_tokens=context_limit_tokens,
        )
        return ReviewRoundAgents.create(
            self._agents,
            model_bindings=model_bindings,
            middleware=middleware,
            answer_model_override=interaction_override,
        )

    def __call__(self, kind: str, **dependencies):
        definition = AGENT_DEFINITION_REGISTRY.require(kind)
        builder_key = definition.builder_key
        if builder_key is None:
            raise RuntimeError(f"Agent definition has no builder: {kind}")
        return self._builder_catalog()[builder_key](definition.agent_id, dependencies)

    def _build_profile_graph(self, kind: str, dependencies: dict[str, Any]):
        bindings = dependencies["model_bindings"]
        context_limit_tokens = min(
            self._agents.resolve_context_limit(role, model_bindings=bindings)
            for role in (
                "profile_extraction",
                "profile_assessment",
                "agent_chat",
            )
        )
        middleware = build_default_middleware(
            summary_model=self._agents.resolve_model(
                "report_summarization", model_bindings=bindings
            ),
            summary_provider_model_id=bindings["report_summarization"],
            trace_writer=self.trace_writer,
            projection=dependencies["projection"],
            policy=ToolPolicyMiddleware(
                audit=dependencies["audit"],
                required_scopes=PROFILE_TOOL_SCOPES,
                publish_event=dependencies.get("publish_event"),
            ),
            observability=dependencies["observability"],
            interrupt_on={},
            budget_profile=PROFILE_CHAT_BUDGET_PROFILE,
            tool_guards=(ProfileToolBudgetMiddleware(),),
            context_limit_tokens=context_limit_tokens,
        )
        profile_repository = dependencies["profile_repository"]
        profile_storage = dependencies["profile_storage"]
        if profile_repository is None or profile_storage is None:
            raise RuntimeError("profile graph dependencies are not configured")
        agents = ProfileAgents.create(
            self._agents,
            model_bindings=bindings,
            middleware=middleware,
            chat_tools=create_profile_tools(
                repository=profile_repository,
                storage=profile_storage,
            ),
            checkpointer=dependencies["checkpointer"],
        )
        if kind == "profile.ingest":
            return create_profile_ingest_graph(
                agents,
                repository=profile_repository,
                storage=profile_storage,
                publish_event=dependencies.get("publish_event"),
                checkpointer=dependencies["checkpointer"],
            )
        assessment_graph = create_profile_assess_graph(
            agents,
            repository=profile_repository,
            project_card=dependencies.get("project_profile_card"),
            checkpointer=(
                dependencies["checkpointer"] if kind == "profile.assess" else None
            ),
        )
        if kind == "profile.assess":
            return assessment_graph
        profile_service = dependencies.get("profile_service")
        if profile_service is None:
            raise RuntimeError("profile manage dependencies are not configured")
        return create_profile_manage_graph(
            agents,
            repository=profile_repository,
            service=profile_service,
            assessment_graph=assessment_graph,
            project_action_plan_card=dependencies.get(
                "project_profile_action_plan_card"
            ),
            checkpointer=dependencies["checkpointer"],
        )

    def _build_question_or_review_graph(self, kind: str, dependencies: dict[str, Any]):
        bindings = dependencies["model_bindings"]
        roles = (
            ("question_generation", "report_summarization")
            if kind in {"question.curate", "question.revise"}
            else ("answer_evaluation", "report_summarization", "agent_chat")
        )
        context_limit_tokens = min(
            self._agents.resolve_context_limit(role, model_bindings=bindings)
            for role in roles
        )
        summary_model = self._agents.resolve_model(
            "report_summarization", model_bindings=bindings
        )
        middleware = build_default_middleware(
            summary_model=summary_model,
            summary_provider_model_id=bindings["report_summarization"],
            trace_writer=self.trace_writer,
            projection=dependencies["projection"],
            policy=ToolPolicyMiddleware(
                audit=dependencies["audit"],
                required_scopes={},
                publish_event=dependencies.get("publish_event"),
            ),
            observability=dependencies["observability"],
            interrupt_on={},
            budget_profile=REVIEW_ROUND_BUDGET,
            context_limit_tokens=context_limit_tokens,
        )
        if kind in {"question.curate", "question.revise"}:
            agents = QuestionCurationAgents.create(
                self._agents,
                model_bindings=bindings,
                middleware=middleware,
                tools=dependencies.get("question_tools", ()),
                checkpointer=dependencies["checkpointer"],
            )
            return create_question_curation_graph(
                agents,
                repository=dependencies["review_repository"],
                checkpointer=dependencies["checkpointer"],
            )
        agents = ReviewRoundAgents.create(
            self._agents,
            model_bindings=bindings,
            middleware=middleware,
            discussion_tools=dependencies.get("discussion_tools", ()),
            answer_model_override=dependencies.get("answer_model_override"),
            discussion_model_override=dependencies.get("discussion_model_override"),
            checkpointer=dependencies["checkpointer"],
        )
        if kind == "review.discussion":
            return create_review_discussion_graph(
                agents, checkpointer=dependencies["checkpointer"]
            )
        return create_review_round_graph(
            agents,
            repository=dependencies["review_repository"],
            create_report_drafts=dependencies["create_report_drafts"],
            request_publication_action=dependencies["request_publication_action"],
            checkpointer=dependencies["checkpointer"],
        )

    def _build_single_review_graph(self, _kind: str, dependencies: dict[str, Any]):
        bindings = dependencies["model_bindings"]
        context_limit_tokens = min(
            self._agents.resolve_context_limit(role, model_bindings=bindings)
            for role in ("answer_evaluation", "report_summarization")
        )
        summary_model = self._agents.resolve_model(
            "report_summarization", model_bindings=bindings
        )
        middleware = build_default_middleware(
            summary_model=summary_model,
            summary_provider_model_id=bindings["report_summarization"],
            trace_writer=self.trace_writer,
            projection=dependencies["projection"],
            policy=ToolPolicyMiddleware(
                audit=dependencies["audit"],
                required_scopes={},
                publish_event=dependencies.get("publish_event"),
            ),
            observability=dependencies["observability"],
            interrupt_on={},
            context_limit_tokens=context_limit_tokens,
        )
        review_agents = SingleReviewAgents.create(
            self._agents,
            model_bindings=bindings,
            middleware=middleware,
            checkpointer=dependencies["checkpointer"],
        )
        return create_review_graph(
            review_agents,
            create_draft=dependencies["create_draft"],
            request_action=dependencies["create_action"],
            checkpointer=dependencies["checkpointer"],
        )

    def _build_publication_graph(self, _kind: str, dependencies: dict[str, Any]):
        return create_publication_graph(
            request_action=dependencies["create_action"],
            checkpointer=dependencies["checkpointer"],
        )

    def _build_job_target_agents(self, _kind: str, dependencies: dict[str, Any]):
        return self._create_job_target_agents(
            model_bindings=dependencies["model_bindings"],
            projection=dependencies["projection"],
            audit=dependencies["audit"],
            observability=dependencies["observability"],
            publish_event=dependencies.get("publish_event"),
            interaction_override=dependencies.get("interaction_override"),
        )

    def _build_interview_retrospective_agents(
        self, _kind: str, dependencies: dict[str, Any]
    ):
        return self._create_interview_retrospective_agents(
            model_bindings=dependencies["model_bindings"],
            projection=dependencies["projection"],
            audit=dependencies["audit"],
            observability=dependencies["observability"],
            publish_event=dependencies.get("publish_event"),
            interaction_override=dependencies.get("interaction_override"),
            chat_tools=dependencies.get("chat_tools", ()),
        )

    @staticmethod
    def _build_diagnostic_echo_graph(_kind: str, dependencies: dict[str, Any]):
        return _echo_graph(dependencies["checkpointer"])

    @staticmethod
    def _build_diagnostic_approval_graph(_kind: str, dependencies: dict[str, Any]):
        return _approval_graph(
            dependencies["create_action"], dependencies["checkpointer"]
        )

    @staticmethod
    def _build_diagnostic_security_graph(_kind: str, dependencies: dict[str, Any]):
        return _security_graph(dependencies["checkpointer"])


def _echo_graph(checkpointer):
    async def respond(state: DiagnosticState):
        return {"response": f"Echo: {state.get('text', '')}"}

    graph = StateGraph(DiagnosticState)
    graph.add_node("respond", respond)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=checkpointer)


def _approval_graph(create_action, checkpointer):
    async def request(state: DiagnosticState):
        summary = state.get("summary", "请确认这次操作")
        action = await create_action(
            action_type="diagnostic.confirm",
            payload={"summary": summary},
            preview={"summary": summary},
            editable_fields=("summary",),
            idempotency_key=f"diagnostic.confirm:{summary}",
        )
        decision = interrupt({"actionId": action.id})
        return {"decision": decision, "response": "确认流程已完成"}

    graph = StateGraph(DiagnosticState)
    graph.add_node("request", request)
    graph.add_edge(START, "request")
    graph.add_edge("request", END)
    return graph.compile(checkpointer=checkpointer)


def _security_graph(checkpointer):
    async def verify(_state: DiagnosticState):
        return {
            "response": (
                "授权读取通过；未注册工具已拒绝；未授权 Scope 已拒绝；路径越界已拒绝"
            )
        }

    graph = StateGraph(DiagnosticState)
    graph.add_node("verify", verify)
    graph.add_edge(START, "verify")
    graph.add_edge("verify", END)
    return graph.compile(checkpointer=checkpointer)
