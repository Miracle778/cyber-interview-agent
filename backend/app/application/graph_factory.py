from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.agent_factory import AgentFactory, ModelOverride
from app.agents.question_curation_agent import QuestionCurationAgents
from app.agents.curation_command_agents import CurationCommandAgents
from app.agents.context_assembly import model_token_counter
from app.agents.single_review_agents import SingleReviewAgents
from app.agents.review_round_agents import ReviewRoundAgents
from app.graphs.publication import create_publication_graph
from app.graphs.question_curation import create_question_curation_graph
from app.graphs.review import create_review_graph
from app.graphs.review_discussion import create_review_discussion_graph
from app.graphs.review_round import create_review_round_graph
from app.middleware.middleware_stack import (
    REVIEW_ROUND_BUDGET,
    build_default_middleware,
)
from app.middleware.tool_policy_middleware import ToolPolicyMiddleware


class DiagnosticState(TypedDict, total=False):
    text: str
    summary: str
    response: str
    decision: dict[str, Any]


class ProductionGraphFactory:
    """Explicit product graph selection; this is not a dynamic graph registry."""

    def __init__(self, agents: AgentFactory) -> None:
        self._agents = agents

    @property
    def trace_writer(self):
        return getattr(self._agents, "trace_writer", None)

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
        summary_model = self._agents.resolve_model("report_summarization", model_bindings=model_bindings)
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
                audit=audit, required_scopes={},
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

    def __call__(self, kind: str, **dependencies):
        if kind in {"question.curate", "question.revise", "review.round", "review.discussion"}:
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
                    audit=dependencies["audit"], required_scopes={},
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
                request_publication_action=dependencies[
                    "request_publication_action"
                ],
                checkpointer=dependencies["checkpointer"],
            )
        if kind == "review.single":
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
                    audit=dependencies["audit"], required_scopes={},
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
        if kind == "knowledge.publish":
            return create_publication_graph(
                request_action=dependencies["create_action"],
                checkpointer=dependencies["checkpointer"],
            )
        if kind == "diagnostic.echo":
            return _echo_graph(dependencies["checkpointer"])
        if kind == "diagnostic.approval":
            return _approval_graph(
                dependencies["create_action"], dependencies["checkpointer"]
            )
        if kind == "diagnostic.security":
            return _security_graph(dependencies["checkpointer"])
        raise ValueError(f"unsupported agent kind: {kind}")


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
                "授权读取通过；未注册工具已拒绝；未授权 Scope 已拒绝；"
                "路径越界已拒绝"
            )
        }

    graph = StateGraph(DiagnosticState)
    graph.add_node("verify", verify)
    graph.add_edge(START, "verify")
    graph.add_edge("verify", END)
    return graph.compile(checkpointer=checkpointer)
