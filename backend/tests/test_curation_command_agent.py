from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.context import AgentContext
from app.agents.context_assembly import (
    AssembledContext,
    ContextMessage,
    ContextResource,
    ContextSummary,
    ContextTurn,
)
from app.agents.curation_command import (
    CurationCommandClassifier,
    CurationCommandModels,
    CurationContextSummarizer,
)
from app.review.curation_command_contracts import (
    CurationCommandPlan,
    CurationDialogueSummary,
)


class RecordingFactory:
    def __init__(self, runnables) -> None:
        self.runnables = iter(runnables)
        self.calls = []

    def create(self, spec, *, model_bindings, checkpointer=None):
        self.calls.append((spec, model_bindings, checkpointer))
        return next(self.runnables)


class RecordingRunnable:
    def __init__(self, structured_response) -> None:
        self.structured_response = structured_response
        self.inputs = []

    async def ainvoke(self, input, config=None, *, context=None):
        self.inputs.append((input, config, context))
        return {"structured_response": self.structured_response}


def _context(tmp_path: Path) -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
        progress_scope=("curation_command", "key-1", "invocation-1"),
    )


def _assembled() -> AssembledContext:
    return AssembledContext(
        current_input="加了备注的重新生成，其他的发布",
        working_state="1. candidate-1 noted=yes\n2. candidate-2 noted=no",
        prior_summary=ContextSummary(
            text="此前用户查看了第 1 题",
            resource_refs=("candidate:candidate-1",),
            decisions=(),
            open_items=("等待确认",),
            through_message_id="message-2",
        ),
        recent_turns=(
            ContextTurn(
                (
                    ContextMessage("message-3", "user", "第 1 题是什么"),
                    ContextMessage("message-4", "assistant", "已展示第 1 题"),
                )
            ),
        ),
        overflow_turns=(),
        selected_resources=(
            ContextResource(
                ref="candidate:candidate-1",
                label="第 1 题",
                content="焦点题正文",
                priority=0,
                required=True,
            ),
        ),
        estimated_input_tokens=120,
        threshold_tokens=800,
    )


def test_models_use_explicit_roles_names_and_no_tools_or_checkpoint() -> None:
    classifier = RecordingRunnable(CurationCommandPlan())
    summarizer = RecordingRunnable(CurationDialogueSummary())
    factory = RecordingFactory((classifier, summarizer))

    models = CurationCommandModels.create(
        factory,
        model_bindings={
            "question_generation": "model-a",
            "report_summarization": "model-b",
        },
        middleware=(object(),),
        context_limit_tokens=16_000,
    )

    classifier_spec, _, classifier_checkpoint = factory.calls[0]
    summarizer_spec, _, summarizer_checkpoint = factory.calls[1]
    assert classifier_spec.role == "question_generation"
    assert classifier_spec.execution_name == "curation_command_classifier"
    assert classifier_spec.tools == ()
    assert summarizer_spec.role == "report_summarization"
    assert summarizer_spec.execution_name == "curation_context_summarizer"
    assert summarizer_spec.tools == ()
    assert classifier_checkpoint is None
    assert summarizer_checkpoint is None
    assert models.context_limit_tokens == 16_000


@pytest.mark.asyncio
async def test_classifier_receives_only_rendered_assembled_context(tmp_path) -> None:
    runnable = RecordingRunnable(
        CurationCommandPlan(response="已理解用户指令")
    )
    classifier = CurationCommandClassifier(runnable)
    assembled = _assembled()

    plan = await classifier.classify(assembled, context=_context(tmp_path))

    prompt = runnable.inputs[0][0]["messages"][0].content
    assert prompt == assembled.render()
    assert plan.response == "已理解用户指令"


@pytest.mark.asyncio
async def test_summarizer_receives_summary_and_overflow_only(tmp_path) -> None:
    runnable = RecordingRunnable(
        CurationDialogueSummary(
            text="用户查看过候选题",
            resource_refs=["candidate:candidate-1"],
            decisions=["保留第 1 题"],
            open_items=["等待发布"],
        )
    )
    summarizer = CurationContextSummarizer(runnable)
    prior = ContextSummary(
        text="旧摘要",
        resource_refs=(),
        decisions=(),
        open_items=(),
        through_message_id="message-2",
    )
    overflow = (
        ContextTurn(
            (
                ContextMessage("message-3", "user", "查看第 1 题"),
                ContextMessage("message-4", "assistant", "这里是题目摘要"),
            )
        ),
    )

    summary = await summarizer.summarize(
        prior_summary=prior,
        overflow_turns=overflow,
        context=_context(tmp_path),
    )

    prompt = runnable.inputs[0][0]["messages"][0].content
    assert "旧摘要" in prompt
    assert "查看第 1 题" in prompt
    assert "这里是题目摘要" in prompt
    assert "FOCUSED_FULL_SOURCE_BODY" not in prompt
    assert summary.through_message_id == "message-4"
    assert summary.resource_refs == ("candidate:candidate-1",)
