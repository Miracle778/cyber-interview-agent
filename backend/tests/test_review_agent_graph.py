from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.context import AgentContext
from app.agents.review import ReviewAgents
from app.agents.review_contracts import AnswerEvaluation
from app.graphs.review import create_review_graph
from app.hitl.models import PendingActionRecord


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


@dataclass
class RecordingAgent:
    result: dict
    calls: list[dict] = field(default_factory=list)

    async def ainvoke(self, input, config=None, *, context=None):
        self.calls.append({"input": input, "config": config, "context": context})
        return self.result


@pytest.mark.asyncio
async def test_review_graph_uses_agent_results_without_provider_state():
    evaluation = AnswerEvaluation(
        score="partial",
        missing_key_points=["隔离性", "持久性"],
        evidence="用户回答提到了原子性",
    )
    evaluator = RecordingAgent({"structured_response": evaluation})
    reporter = RecordingAgent(
        {"messages": [AIMessage(content="# 单题复习\n\n- 评分：partial")]}
    )
    agents = ReviewAgents(evaluator=evaluator, reporter=reporter)
    graph = create_review_graph(agents)
    context = AgentContext(
        workspace_id="workspace-1",
        workspace_root=Path("/workspace"),
        session_id="session-1",
        run_id="run-1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )

    result = await graph.ainvoke(
        {"question": QUESTION, "user_answer": "事务保证原子性和一致性"},
        {"configurable": {"thread_id": "session-1"}},
        context=context,
    )

    assert result["evaluation"] == evaluation.model_dump()
    assert result["report_markdown"].startswith("# 单题复习")
    assert evaluator.calls[0]["context"] is context
    assert reporter.calls[0]["context"] is context
    assert evaluator.calls[0]["config"]["configurable"] == {
        "thread_id": "session-1:answer_evaluation",
    }
    assert reporter.calls[0]["config"]["configurable"] == {
        "thread_id": "session-1:report_summarization",
    }
    assert "api_key" not in result
    assert "provider" not in result


@pytest.mark.asyncio
async def test_review_agents_reject_empty_report():
    evaluation = AnswerEvaluation(
        score="good", missing_key_points=[], evidence="回答完整"
    )
    agents = ReviewAgents(
        evaluator=RecordingAgent({"structured_response": evaluation}),
        reporter=RecordingAgent({"messages": [AIMessage(content="   ")]}),
    )
    context = AgentContext(
        workspace_id="w1",
        workspace_root=Path("/workspace"),
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )

    with pytest.raises(ValueError, match="模型未生成复习报告"):
        await agents.report(
            question=QUESTION,
            user_answer="完整回答",
            evaluation=evaluation,
            context=context,
            config={"configurable": {"thread_id": "s1"}},
        )


@pytest.mark.asyncio
async def test_review_graph_keeps_draft_and_publication_as_explicit_nodes():
    evaluation = AnswerEvaluation(
        score="partial", missing_key_points=["隔离性"], evidence="提到原子性"
    )
    agents = ReviewAgents(
        evaluator=RecordingAgent({"structured_response": evaluation}),
        reporter=RecordingAgent(
            {"messages": [AIMessage(content="# 单题复习\n\n需要补充隔离性")]}
        ),
    )
    draft_calls = []
    action_calls = []

    async def create_draft(**kwargs):
        draft_calls.append(kwargs)
        return SimpleNamespace(id="draft-1", version=1, content_hash="hash-1")

    async def request_action(**kwargs):
        action_calls.append(kwargs)
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
            created_at="2026-07-13T00:00:00Z",
            resolved_at=None,
        )

    graph = create_review_graph(
        agents,
        create_draft=create_draft,
        request_action=request_action,
        checkpointer=InMemorySaver(),
    )
    context = AgentContext(
        workspace_id="w1",
        workspace_root=Path("/workspace"),
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )
    config = {"configurable": {"thread_id": "s1"}}

    interrupted = await graph.ainvoke(
        {"question": QUESTION, "user_answer": "原子性和一致性"},
        config,
        context=context,
    )
    resumed = await graph.ainvoke(
        Command(resume={"decision": "rejected", "reason": "revise"}),
        config,
        context=context,
    )

    assert interrupted["report_draft_id"] == "draft-1"
    assert interrupted["__interrupt__"][0].value == {"actionId": "action-1"}
    assert draft_calls[0]["source_refs"] == ("q1",)
    assert action_calls[0]["idempotency_key"] == "knowledge.publish:draft-1:1:hash-1"
    assert resumed["response"] == "单题复习报告未发布：revise"
