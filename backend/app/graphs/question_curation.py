from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.context import AgentContext
from app.agents.question_curation import QuestionCurationAgent


class QuestionCurationState(TypedDict, total=False):
    source_excerpts: list[str]
    similar_questions: list[str]
    rewrite_feedback: str | None
    candidates: list[dict[str, Any]]


def create_question_curation_graph(
    agent: QuestionCurationAgent, *, checkpointer=None
):
    async def generate(
        state: QuestionCurationState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        batch = await agent.generate(
            source_excerpts=tuple(state.get("source_excerpts", ())),
            similar_questions=tuple(state.get("similar_questions", ())),
            rewrite_feedback=state.get("rewrite_feedback"),
            context=runtime.context,
            config=dict(config),
        )
        return {"candidates": batch.model_dump()["candidates"]}

    graph = StateGraph(QuestionCurationState, context_schema=AgentContext)
    graph.add_node("generate_candidates", generate)
    graph.add_edge(START, "generate_candidates")
    graph.add_edge("generate_candidates", END)
    return graph.compile(checkpointer=checkpointer)
