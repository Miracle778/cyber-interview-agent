from __future__ import annotations

import pytest

from app.application.session_service import MessageRecord
from app.agents.context_assembly import ContextSummary
from app.review.curation_command_contracts import CurationCommandPlan
from app.review.curation_context import (
    CurationCommandInterpreter,
    CurationContextAdapter,
)
from app.review.curation_commands import CurationCommandService
from app.review.models import CurationSummary


def _message(
    index: int,
    role: str,
    *,
    candidate_ids: tuple[str, ...] = (),
) -> MessageRecord:
    return MessageRecord(
        id=f"message-{index}",
        execution_id="run-1",
        role=role,
        content=f"message content {index}",
        message_kind="text" if role == "user" else "command_receipt",
        payload={"candidateIds": candidate_ids} if candidate_ids else {},
        created_at=f"2026-07-15 10:00:{index:02d}",
    )


def test_adapter_recovers_valid_focus_and_builds_complete_turns() -> None:
    messages = tuple(
        _message(
            index,
            "user" if index % 2 == 0 else "assistant",
            candidate_ids=("candidate-6",) if index == 11 else (),
        )
        for index in range(12)
    )
    candidates = (
        {
            "id": "candidate-1",
            "ordinal": 1,
            "title": "普通题",
            "status": "review_pending",
            "recommendation": "suggest_edit",
            "review_note": "",
            "question": {
                "question_text": "non focus question",
                "reference_answer": "NON_FOCUS_SECRET_ANSWER",
                "key_points": ["non focus key"],
                "follow_ups": [],
            },
        },
        {
            "id": "candidate-6",
            "ordinal": 6,
            "title": "MVCC",
            "status": "review_pending",
            "recommendation": "recommend_confirm",
            "review_note": "补充边界",
            "question": {
                "question_text": "Read View 如何判断可见性？",
                "reference_answer": "FOCUSED_FULL_ANSWER",
                "key_points": ["活跃事务集合"],
                "follow_ups": ["当前读呢？"],
            },
        },
    )

    focus = CurationContextAdapter.recover_focus(
        messages, {"candidate-1", "candidate-6"}
    )
    material = CurationContextAdapter.build_material(
        current_input="这题发布吧",
        summary_version=3,
        focused_candidate_ids=focus,
        prior_summary=ContextSummary.empty(),
        summarized_through_message_id=None,
        messages=messages,
        candidates=candidates,
    )

    assert focus == ("candidate-6",)
    assert len(material.turns) == 6
    assert all(len(turn.messages) == 2 for turn in material.turns)
    assert len(material.resources) == 1
    assert material.resources[0].required is True
    assert "FOCUSED_FULL_ANSWER" in material.resources[0].content
    assert "NON_FOCUS_SECRET_ANSWER" not in material.working_state
    assert "普通题" in material.working_state


class RecordingClassifier:
    def __init__(self) -> None:
        self.calls = []

    async def classify(self, assembled, *, context):
        self.calls.append((assembled, context))
        return CurationCommandPlan(clarification="模型解释结果")


def _summary() -> CurationSummary:
    return CurationSummary(
        items=(
            {
                "ordinal": 1,
                "candidateId": "candidate-1",
                "recommendation": "recommend_confirm",
            },
        )
    )


@pytest.mark.asyncio
async def test_interpreter_does_not_load_context_for_deterministic_command() -> None:
    loaded = 0
    classifier = RecordingClassifier()

    async def context_provider():
        nonlocal loaded
        loaded += 1
        return object(), object()

    plan = await CurationCommandInterpreter(
        CurationCommandService(), classifier
    ).interpret(
        text="发布第 1 题",
        summary=_summary(),
        focused_candidate_ids=(),
        context_provider=context_provider,
    )

    assert plan.publish.ordinals == [1]
    assert loaded == 0
    assert classifier.calls == []


@pytest.mark.asyncio
async def test_interpreter_loads_context_once_for_free_language() -> None:
    loaded = 0
    classifier = RecordingClassifier()
    assembled = object()
    invocation_context = object()

    async def context_provider():
        nonlocal loaded
        loaded += 1
        return assembled, invocation_context

    plan = await CurationCommandInterpreter(
        CurationCommandService(), classifier
    ).interpret(
        text="按我备注的处理，剩下的照常",
        summary=_summary(),
        focused_candidate_ids=(),
        context_provider=context_provider,
    )

    assert plan.clarification == "模型解释结果"
    assert loaded == 1
    assert classifier.calls == [(assembled, invocation_context)]
