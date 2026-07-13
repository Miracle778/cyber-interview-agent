from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.agents.context import AgentContext
from app.agents.review import ReviewAgents
from app.agents.review_contracts import (
    AnswerEvaluation,
    SingleReviewInput,
    SingleReviewState,
)


def create_review_graph(
    agents: ReviewAgents,
    *,
    create_draft=None,
    request_action=None,
    checkpointer=None,
):
    if (create_draft is None) != (request_action is None):
        raise ValueError("draft creation and publication approval must be configured together")
    def validated_input(state: SingleReviewState) -> SingleReviewInput:
        return SingleReviewInput.model_validate(
            {"question": state["question"], "user_answer": state["user_answer"]}
        )

    async def evaluate(
        state: SingleReviewState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        value = validated_input(state)
        evaluation = await agents.evaluate(
            question=value.question,
            user_answer=value.user_answer,
            context=runtime.context,
            config=dict(config),
        )
        return {"evaluation": evaluation.model_dump()}

    async def report(
        state: SingleReviewState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, str]:
        value = validated_input(state)
        markdown = await agents.report(
            question=value.question,
            user_answer=value.user_answer,
            evaluation=AnswerEvaluation.model_validate(state["evaluation"]),
            context=runtime.context,
            config=dict(config),
        )
        return {"report_markdown": markdown}

    async def save_draft(state: SingleReviewState) -> dict[str, Any]:
        value = validated_input(state)
        draft = await create_draft(
            title=f"单题复习：{value.question.title}",
            markdown=state["report_markdown"],
            source_refs=(value.question.id,),
            relation_refs=tuple(value.question.topics),
        )
        return {
            "report_draft_id": draft.id,
            "report_draft_version": draft.version,
            "report_content_hash": draft.content_hash,
        }

    async def request_publication(state: SingleReviewState) -> dict[str, Any]:
        value = validated_input(state)
        action = await request_action(
            action_type="knowledge.publish",
            payload={
                "draftId": state["report_draft_id"],
                "draftVersion": state["report_draft_version"],
                "contentHash": state["report_content_hash"],
                "title": value.question.title,
                "markdown": state["report_markdown"],
            },
            preview={
                "title": value.question.title,
                "markdown": state["report_markdown"],
                "draftId": state["report_draft_id"],
                "question": value.question.model_dump(by_alias=True),
                "evaluation": state["evaluation"],
            },
            editable_fields=("title", "markdown"),
            idempotency_key=(
                f"knowledge.publish:{state['report_draft_id']}:"
                f"{state['report_draft_version']}:{state['report_content_hash']}"
            ),
        )
        decision = interrupt({"actionId": action.id})
        response = (
            "单题复习报告已发布"
            if decision.get("decision") == "approved"
            else f"单题复习报告未发布：{decision.get('reason', '未说明原因')}"
        )
        return {"action_id": action.id, "decision": decision, "response": response}

    graph = StateGraph(SingleReviewState, context_schema=AgentContext)
    graph.add_node("evaluate_answer", evaluate)
    graph.add_node("create_report", report)
    graph.add_edge(START, "evaluate_answer")
    graph.add_edge("evaluate_answer", "create_report")
    if create_draft is None:
        graph.add_edge("create_report", END)
    else:
        graph.add_node("save_draft", save_draft)
        graph.add_node("request_publication", request_publication)
        graph.add_edge("create_report", "save_draft")
        graph.add_edge("save_draft", "request_publication")
        graph.add_edge("request_publication", END)
    return graph.compile(checkpointer=checkpointer)
