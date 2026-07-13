from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.hitl.models import PendingActionRecord


class KnowledgePublicationState(TypedDict, total=False):
    draftId: str
    draftVersion: int
    contentHash: str
    title: str
    markdown: str
    decision: dict[str, Any]
    response: str


ActionRequester = Callable[..., Awaitable[PendingActionRecord]]


def create_publication_graph(*, request_action: ActionRequester, checkpointer):
    async def request_approval(state: KnowledgePublicationState):
        payload = {
            "draftId": state["draftId"],
            "draftVersion": state["draftVersion"],
            "contentHash": state["contentHash"],
            "title": state["title"],
            "markdown": state["markdown"],
        }
        action = await request_action(
            action_type="knowledge.publish",
            payload=payload,
            preview={"title": state["title"], "markdown": state["markdown"]},
            editable_fields=("title", "markdown"),
            idempotency_key=(
                f"knowledge.publish:{state['draftId']}:"
                f"{state['draftVersion']}:{state['contentHash']}"
            ),
        )
        decision = interrupt({"actionId": action.id})
        response = (
            "知识草稿已发布"
            if decision.get("decision") == "approved"
            else f"知识草稿未发布：{decision.get('reason', '未说明原因')}"
        )
        return {"decision": decision, "response": response}

    graph = StateGraph(KnowledgePublicationState)
    graph.add_node("request_approval", request_approval)
    graph.add_edge(START, "request_approval")
    graph.add_edge("request_approval", END)
    return graph.compile(checkpointer=checkpointer)
