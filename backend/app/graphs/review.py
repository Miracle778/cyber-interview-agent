from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.context import AgentContext
from app.agents.review import ReviewAgents
from app.agents.review_contracts import (
    AnswerEvaluation,
    SingleReviewInput,
    SingleReviewState,
)


def create_review_graph(agents: ReviewAgents):
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

    graph = StateGraph(SingleReviewState, context_schema=AgentContext)
    graph.add_node("evaluate_answer", evaluate)
    graph.add_node("create_report", report)
    graph.add_edge(START, "evaluate_answer")
    graph.add_edge("evaluate_answer", "create_report")
    graph.add_edge("create_report", END)
    return graph.compile()
