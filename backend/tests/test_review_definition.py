from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from langgraph.types import Command

from app.agents.review_contracts import AnswerEvaluation
from app.agents.review_definition import (
    create_single_review_graph,
    single_review_definition,
)
from app.db.runtime_database import connect_runtime_database
from app.hitl.models import PendingActionRecord
from app.runtime.checkpoints import RuntimeCheckpointer
from app.runtime.graph_build_context import (
    GraphBuildContext,
    unavailable_tool_invoker,
)


QUESTION = {
    "id": "q1",
    "title": "事务特性",
    "questionText": "什么是事务的 ACID？",
    "referenceAnswer": "原子性、一致性、隔离性、持久性",
    "topics": ["database"],
    "difficulty": "medium",
    "keyPoints": ["原子性", "一致性", "隔离性", "持久性"],
    "followUps": [],
    "mastery": "weak",
}


class FakeModelInvoker:
    def __init__(self) -> None:
        self.roles: list[str] = []

    async def invoke_structured(self, *, role, schema, messages):
        del messages
        self.roles.append(role)
        return schema.model_validate(
            {
                "score": "partial",
                "missing_key_points": ["隔离性", "持久性"],
                "evidence": "用户回答提到了原子性",
            }
        )

    async def stream_text(self, *, role, messages) -> AsyncIterator[str]:
        del messages
        self.roles.append(role)
        for chunk in ("# 单题复习报告\n", "\n- 评分：partial\n"):
            yield chunk


def _action() -> PendingActionRecord:
    return PendingActionRecord(
        id="action-1",
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        action_type="knowledge.publish",
        payload={},
        preview={},
        editable_fields=(),
        status="pending",
        version=1,
        idempotency_key="publish-1",
        created_at="2026-07-12T00:00:00Z",
        resolved_at=None,
    )


@pytest.mark.asyncio
async def test_single_review_uses_roles_creates_draft_and_interrupts(
    tmp_path,
) -> None:
    model = FakeModelInvoker()
    draft_calls = []
    action_calls = []

    async def create_draft(**kwargs):
        draft_calls.append(kwargs)
        return SimpleNamespace(
            id="draft-1", version=1, content_hash="hash-1"
        )

    async def request_action(**kwargs):
        action_calls.append(kwargs)
        return _action()

    connect_runtime_database(tmp_path).close()
    checkpointer = RuntimeCheckpointer(tmp_path)
    async with checkpointer.open() as saver:
        graph = create_single_review_graph(
            GraphBuildContext(
                checkpointer=saver,
                invoke_tool=unavailable_tool_invoker,
                invoke_model=model,
                create_draft=create_draft,
                request_action=request_action,
            )
        )
        result = await graph.ainvoke(
            {"question": QUESTION, "user_answer": "事务保证原子性和一致性"},
            {"configurable": {"thread_id": "s1"}},
        )

        assert model.roles == ["answer_evaluation", "report_summarization"]
        assert result["evaluation"] == AnswerEvaluation(
            score="partial",
            missing_key_points=["隔离性", "持久性"],
            evidence="用户回答提到了原子性",
        ).model_dump()
        assert result["report_draft_id"] == "draft-1"
        assert draft_calls[0]["source_refs"] == ("q1",)
        assert action_calls[0]["action_type"] == "knowledge.publish"
        assert result["__interrupt__"][0].value == {"actionId": "action-1"}

        resumed = await graph.ainvoke(
            Command(resume={"decision": "rejected", "reason": "稍后处理"}),
            {"configurable": {"thread_id": "s1"}},
        )

    assert resumed["decision"]["decision"] == "rejected"
    assert resumed["response"] == "单题复习报告未发布：稍后处理"


def test_single_review_definition_declares_runtime_security_contract() -> None:
    definition = single_review_definition()

    assert definition.graph_id == "review.single"
    assert definition.graph_version == 1
    assert definition.required_model_roles == {
        "answer_evaluation",
        "report_summarization",
    }
    assert definition.allowed_tools == {
        "read_source",
        "read_active_knowledge",
        "write_review_draft",
    }
    assert definition.allowed_scopes == {
        "review.sources",
        "review.drafts",
        "knowledge.active",
    }
