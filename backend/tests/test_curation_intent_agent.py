from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.context import AgentContext
from app.agents.curation_intent import CurationIntentAgent, CurationIntentPlan


class RecordingAgent:
    def __init__(self) -> None:
        self.input = None

    async def ainvoke(self, input, config=None, *, context=None):
        self.input = input
        return {
            "structured_response": CurationIntentPlan(
                response="题目、参考答案和关键点"
            )
        }


@pytest.mark.asyncio
async def test_question_content_context_includes_key_points_and_follow_ups(
    tmp_path: Path,
) -> None:
    runnable = RecordingAgent()
    agent = CurationIntentAgent(runnable)

    await agent.resolve(
        text="第 1 题是怎么写的？",
        candidates=(
            {
                "ordinal": 1,
                "title": "MVCC 可见性",
                "recommendation": "recommend_confirm",
                "status": "review_pending",
                "question": {
                    "question_text": "Read View 如何判断版本可见性？",
                    "reference_answer": "比较事务 ID 与活跃事务集合。",
                    "key_points": ["上下界", "活跃事务集合"],
                    "follow_ups": ["当前读与快照读有什么区别？"],
                },
            },
        ),
        context=AgentContext(
            workspace_id="w1",
            workspace_root=tmp_path,
            session_id="s1",
            run_id="r1",
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
        ),
        conversation=(
            {
                "role": "assistant",
                "content": "第 6 题：事务隔离级别",
                "candidateOrdinals": (6,),
            },
        ),
    )

    prompt = runnable.input["messages"][0].content
    assert "关键点=上下界、活跃事务集合" in prompt
    assert "必要追问=当前读与快照读有什么区别？" in prompt
    assert "assistant [关联候选: 第6题]: 第 6 题：事务隔离级别" in prompt
