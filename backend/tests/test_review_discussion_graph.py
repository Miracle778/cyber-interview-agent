from pathlib import Path

import pytest

from app.agents.context import AgentContext
from app.graphs.review_discussion import create_review_discussion_graph
from app.review.models import QuestionSnapshot


class RecordingDiscussionAgents:
    def __init__(self) -> None:
        self.calls = []

    async def discuss(self, **values):
        self.calls.append(values)
        return "Read View 会按事务上下界和活跃集合判断可见性。"


def _context() -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=Path("/workspace"),
        session_id="discussion-1",
        run_id="run-1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )


def _question() -> QuestionSnapshot:
    return QuestionSnapshot(
        question_id="q1",
        document_id="d1",
        content_hash="a" * 64,
        title="MVCC",
        question_text="Read View 如何判断可见性？",
        reference_answer="比较上下界和活跃事务集合。",
        topics=("database",),
        difficulty="medium",
        key_points=("上下界", "活跃集合"),
        follow_ups=(),
    )


@pytest.mark.asyncio
async def test_discussion_graph_uses_frozen_evidence_without_parent_state() -> None:
    agents = RecordingDiscussionAgents()
    graph = create_review_discussion_graph(agents)

    result = await graph.ainvoke(
        {
            "question_snapshot": _question(),
            "attempt_evidence": {"score": "partial", "missing": ["活跃集合"]},
            "message": "请解释遗漏点",
            "parent_round_id": "round-1",
        },
        context=_context(),
    )

    assert result["response"].startswith("Read View")
    assert agents.calls[0]["context"].session_id == "discussion-1"
    assert "parent_round_id" not in agents.calls[0]


@pytest.mark.asyncio
async def test_discussion_graph_can_initialize_context_without_calling_model() -> None:
    agents = RecordingDiscussionAgents()
    graph = create_review_discussion_graph(agents)

    result = await graph.ainvoke(
        {
            "question_snapshot": _question(),
            "attempt_evidence": {
                "attemptId": "attempt-1",
                "answer": "我只提到了事务上下界",
                "followUpAnswer": "补充活跃事务集合",
            },
            "message": "",
            "parent_round_id": "round-1",
        },
        context=_context(),
    )

    assert agents.calls == []
    assert result["attempt_evidence"]["answer"] == "我只提到了事务上下界"
