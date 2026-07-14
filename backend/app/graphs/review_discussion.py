from __future__ import annotations

from typing import Any, Protocol, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.context import AgentContext
from app.review.models import QuestionSnapshot
class DiscussionAgents(Protocol):
    async def discuss(self, **kwargs: Any) -> str: ...


class ReviewDiscussionState(TypedDict, total=False):
    question_snapshot: QuestionSnapshot
    attempt_evidence: dict[str, Any]
    message: str
    parent_round_id: str
    response: str


def create_review_discussion_graph(agents: DiscussionAgents, *, checkpointer=None):
    async def discuss(
        state: ReviewDiscussionState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, str]:
        raw_question = state["question_snapshot"]
        question = (
            raw_question
            if isinstance(raw_question, QuestionSnapshot)
            else QuestionSnapshot(
                question_id=str(raw_question["question_id"]),
                document_id=str(raw_question["document_id"]),
                content_hash=str(raw_question["content_hash"]),
                title=str(raw_question["title"]),
                question_text=str(raw_question["question_text"]),
                reference_answer=str(raw_question["reference_answer"]),
                topics=tuple(raw_question["topics"]),
                difficulty=raw_question["difficulty"],
                key_points=tuple(raw_question["key_points"]),
                follow_ups=tuple(raw_question["follow_ups"]),
            )
        )
        response = await agents.discuss(
            question=question,
            attempt_evidence=dict(state["attempt_evidence"]),
            message=state["message"],
            context=runtime.context,
            config=dict(config),
        )
        return {"response": response}

    graph = StateGraph(ReviewDiscussionState, context_schema=AgentContext)
    graph.add_node("discuss", discuss)
    graph.add_edge(START, "discuss")
    graph.add_edge("discuss", END)
    return graph.compile(checkpointer=checkpointer)
