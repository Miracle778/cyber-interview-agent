from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessageChunk

from app.agents.context import AgentContext
from app.agents.context_assembly import (
    AssembledContext,
    ContextMessage,
    ContextResource,
    ContextSummary,
    ContextTurn,
)
from app.agents.curation_command_agents import (
    CurationCommandClassifier,
    CurationCommandAgents,
    CurationCommandResponder,
    CurationContextSummarizer,
)
from app.agents.agent_factory import ModelOverride
from app.review.curation_command_contracts import (
    CurationCommandPlan,
    CurationDialogueSummary,
)


class RecordingFactory:
    def __init__(self, runnables) -> None:
        self.runnables = iter(runnables)
        self.calls = []

    def create(
        self,
        spec,
        *,
        component_id,
        model_bindings,
        model_override=None,
        checkpointer=None,
    ):
        assert component_id == spec.execution_name
        self.calls.append(
            (spec, model_bindings, model_override, checkpointer)
        )
        return next(self.runnables)


class RecordingRunnable:
    def __init__(self, structured_response) -> None:
        self.structured_response = structured_response
        self.inputs = []

    async def ainvoke(self, input, config=None, *, context=None):
        self.inputs.append((input, config, context))
        return {"structured_response": self.structured_response}


class StreamingRunnable:
    async def astream(self, input, config=None, *, context=None, **kwargs):
        assert input["messages"][0].content == "rendered context"
        yield {"type": "messages", "data": (AIMessageChunk(content="你"), {})}
        yield {"type": "messages", "data": (AIMessageChunk(content="好"), {})}


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
    responder = StreamingRunnable()
    factory = RecordingFactory((classifier, summarizer, responder))

    models = CurationCommandAgents.create(
        factory,
        model_bindings={
            "question_generation": "model-a",
            "report_summarization": "model-b",
        },
        middleware=(object(),),
        context_limit_tokens=16_000,
    )

    classifier_spec, _, classifier_override, classifier_checkpoint = factory.calls[0]
    summarizer_spec, _, summarizer_override, summarizer_checkpoint = factory.calls[1]
    responder_spec, _, responder_override, responder_checkpoint = factory.calls[2]
    assert classifier_spec.role == "question_generation"
    assert classifier_spec.execution_name == "curation_command_classifier"
    assert classifier_spec.tools == ()
    assert summarizer_spec.role == "report_summarization"
    assert summarizer_spec.execution_name == "curation_context_summarizer"
    assert summarizer_spec.tools == ()
    assert responder_spec.execution_name == "curation_command_responder"
    assert responder_spec.tools == ()
    assert classifier_checkpoint is None
    assert summarizer_checkpoint is None
    assert classifier_override is None
    assert summarizer_override is None
    assert responder_override is None
    assert responder_checkpoint is None
    assert models.context_limit_tokens == 16_000


def test_interaction_override_only_changes_classifier_model() -> None:
    classifier = RecordingRunnable(CurationCommandPlan())
    summarizer = RecordingRunnable(CurationDialogueSummary())
    responder = StreamingRunnable()
    factory = RecordingFactory((classifier, summarizer, responder))
    override = ModelOverride(
        provider_model_id="chosen-model",
        reasoning_effort="high",
    )

    CurationCommandAgents.create(
        factory,
        model_bindings={
            "question_generation": "default-model",
            "report_summarization": "summary-model",
        },
        interaction_override=override,
        context_limit_tokens=16_000,
    )

    assert factory.calls[0][2] == override
    assert factory.calls[1][2] is None
    assert factory.calls[2][2] == override


@pytest.mark.asyncio
async def test_responder_streams_only_real_assistant_text(tmp_path) -> None:
    responder = CurationCommandResponder(StreamingRunnable())

    chunks = [
        chunk
        async for chunk in responder.astream(
            "rendered context", context=_context(tmp_path)
        )
    ]

    assert chunks == ["你", "好"]


@pytest.mark.asyncio
async def test_classifier_receives_only_rendered_assembled_context(tmp_path) -> None:
    runnable = RecordingRunnable(CurationCommandPlan(clarification="请明确题号"))
    classifier = CurationCommandClassifier(runnable)
    assembled = _assembled()

    plan = await classifier.classify(assembled, context=_context(tmp_path))

    prompt = runnable.inputs[0][0]["messages"][0].content
    assert prompt == assembled.render()
    assert plan.clarification == "请明确题号"


def test_classifier_contract_contains_no_user_facing_response() -> None:
    assert "response" not in CurationCommandPlan.model_fields


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
