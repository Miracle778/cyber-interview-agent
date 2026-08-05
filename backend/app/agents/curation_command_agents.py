from __future__ import annotations

from dataclasses import dataclass

from langchain_core.messages import AIMessageChunk, HumanMessage

from app.agents.context import AgentContext
from app.agents.context_assembly import (
    AssembledContext,
    ContextSummary,
    ContextTurn,
    TokenCounter,
)
from app.agents.agent_factory import AgentSpec, ModelOverride, RegisteredAgentFactory
from app.agents.agent_protocols import AgentRunnable, StreamingAgentRunnable
from app.agents.prompts.curation_command_prompts import (
    CURATION_COMMAND_CLASSIFIER_PROMPT,
    CURATION_COMMAND_RESPONDER_PROMPT,
    CURATION_CONTEXT_SUMMARIZER_PROMPT,
    render_curation_summary_input,
)
from app.review.curation_command_contracts import (
    CurationCommandPlan,
    CurationDialogueSummary,
)


@dataclass(frozen=True, slots=True)
class CurationCommandClassifier:
    runnable: AgentRunnable

    async def classify(
        self, assembled: AssembledContext, *, context: AgentContext
    ) -> CurationCommandPlan:
        result = await self.runnable.ainvoke(
            {"messages": [HumanMessage(content=assembled.render())]},
            context=context,
        )
        return CurationCommandPlan.model_validate(result["structured_response"])


@dataclass(frozen=True, slots=True)
class CurationContextSummarizer:
    runnable: AgentRunnable

    async def summarize(
        self,
        *,
        prior_summary: ContextSummary,
        overflow_turns: tuple[ContextTurn, ...],
        context: AgentContext,
    ) -> ContextSummary:
        if not overflow_turns:
            return prior_summary
        result = await self.runnable.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=render_curation_summary_input(
                            prior_summary, overflow_turns
                        )
                    )
                ]
            },
            context=context,
        )
        structured = CurationDialogueSummary.model_validate(
            result["structured_response"]
        )
        return ContextSummary(
            text=structured.text,
            resource_refs=tuple(structured.resource_refs),
            decisions=tuple(structured.decisions),
            open_items=tuple(structured.open_items),
            through_message_id=overflow_turns[-1].messages[-1].id,
        )


@dataclass(frozen=True, slots=True)
class CurationCommandResponder:
    runnable: StreamingAgentRunnable

    async def astream(self, rendered_context: str, *, context: AgentContext):
        async for part in self.runnable.astream(
            {"messages": [HumanMessage(content=rendered_context)]},
            context=context,
            stream_mode=["messages"],
            version="v2",
        ):
            if not isinstance(part, dict) or part.get("type") != "messages":
                continue
            message, _metadata = part.get("data", (None, {}))
            if isinstance(message, AIMessageChunk) and message.text:
                yield message.text


@dataclass(frozen=True, slots=True)
class CurationCommandAgents:
    classifier: CurationCommandClassifier
    summarizer: CurationContextSummarizer
    responder: CurationCommandResponder
    context_limit_tokens: int
    token_counter: TokenCounter = len

    @classmethod
    def create(
        cls,
        factory: RegisteredAgentFactory,
        *,
        model_bindings,
        interaction_override: ModelOverride | None = None,
        middleware=(),
        context_limit_tokens: int,
        token_counter: TokenCounter = len,
    ) -> CurationCommandAgents:
        classifier = factory.create(
            AgentSpec(
                role="question_generation",
                execution_name="curation_command_classifier",
                prompt=CURATION_COMMAND_CLASSIFIER_PROMPT,
                middleware=tuple(middleware),
                response_format=CurationCommandPlan,
            ),
            component_id="curation_command_classifier",
            model_bindings=model_bindings,
            model_override=interaction_override,
            checkpointer=None,
        )
        summarizer = factory.create(
            AgentSpec(
                role="report_summarization",
                execution_name="curation_context_summarizer",
                prompt=CURATION_CONTEXT_SUMMARIZER_PROMPT,
                middleware=tuple(middleware),
                response_format=CurationDialogueSummary,
            ),
            component_id="curation_context_summarizer",
            model_bindings=model_bindings,
            model_override=None,
            checkpointer=None,
        )
        responder = factory.create(
            AgentSpec(
                role="question_generation",
                execution_name="curation_command_responder",
                prompt=CURATION_COMMAND_RESPONDER_PROMPT,
                middleware=tuple(middleware),
            ),
            component_id="curation_command_responder",
            model_bindings=model_bindings,
            model_override=interaction_override,
            checkpointer=None,
        )
        return cls(
            classifier=CurationCommandClassifier(classifier),
            summarizer=CurationContextSummarizer(summarizer),
            responder=CurationCommandResponder(responder),
            context_limit_tokens=context_limit_tokens,
            token_counter=token_counter,
        )
