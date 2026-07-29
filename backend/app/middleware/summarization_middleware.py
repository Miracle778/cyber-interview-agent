from __future__ import annotations

import asyncio
from uuid import uuid4

from langchain.agents.middleware import SummarizationMiddleware
from langchain.agents.middleware.summarization import get_buffer_string

from app.diagnostics.agent_trace import TraceIdentity, stable_trace_operation_id
from app.middleware.agent_trace_middleware import safe_error_payload
from app.middleware.usage_projection_middleware import ContextUsageProjection


class ProjectingSummarizationMiddleware(SummarizationMiddleware):
    """Use official compaction and project only a content-free product indicator."""

    def __init__(
        self,
        *args,
        projection,
        threshold_tokens: int,
        trace_writer=None,
        provider_model_id: str = "unknown",
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._projection = projection
        self.threshold_tokens = threshold_tokens
        self._trace_writer = trace_writer
        self._provider_model_id = provider_model_id

    async def abefore_model(self, state, runtime):
        current_tokens = self.token_counter(state.get("messages", ()))
        try:
            self._projection.record_context_usage(
                runtime.context,
                ContextUsageProjection(
                    current_tokens=current_tokens,
                    threshold_tokens=self.threshold_tokens,
                ),
            )
        except Exception:
            self._projection.warning(runtime.context, "context_usage_projection_failed")
        update = await self._summarize_with_trace(state, runtime)
        if update is None:
            return None
        try:
            self._projection.mark_context_compacted(runtime.context)
        except Exception:
            self._projection.warning(runtime.context, "summary_projection_failed")
        return update

    async def _summarize_with_trace(self, state, runtime):
        messages = state["messages"]
        self._ensure_message_ids(messages)
        total_tokens = self.token_counter(messages)
        if not self._should_summarize(messages, total_tokens):
            return None
        cutoff_index = self._determine_cutoff_index(messages)
        if cutoff_index <= 0:
            return None
        messages_to_summarize, preserved_messages = self._partition_messages(
            messages, cutoff_index
        )
        summary = await self._create_traced_summary(
            messages_to_summarize, runtime.context
        )
        new_messages = self._build_new_messages(summary)
        from langchain.messages import RemoveMessage
        from langgraph.graph.message import REMOVE_ALL_MESSAGES

        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *new_messages,
                *preserved_messages,
            ]
        }

    async def _create_traced_summary(self, messages, context) -> str:
        if not messages:
            return "No previous conversation history."
        trimmed_messages = self._trim_messages_for_summary(messages)
        if not trimmed_messages:
            return "Previous conversation was too long to summarize."
        formatted_messages = get_buffer_string(trimmed_messages, format="xml")
        prompt = self.summary_prompt.format(messages=formatted_messages).rstrip()
        invocation_id = str(uuid4())
        identity = TraceIdentity(
            workspace_id=context.workspace_id,
            workspace_root=context.workspace_root,
            session_id=context.session_id,
            run_id=context.run_id,
            agent_role="report_summarization",
            agent_name="context_summary",
            invocation_id=invocation_id,
            operation_id=stable_trace_operation_id(
                context.run_id,
                invocation_id,
                "model",
            ),
            parent_operation_id=stable_trace_operation_id(
                context.run_id,
                "report_summarization",
                "context_summary",
                "agent",
            ),
            operation_kind="model",
        )
        await self._append_trace(
            context,
            identity,
            "model.request",
            {"provider_model_id": self._provider_model_id, "prompt": prompt},
        )
        try:
            response = await self.model.ainvoke(
                prompt,
                config={"metadata": {"lc_source": "summarization"}},
            )
        except Exception as error:
            await self._append_trace(
                context,
                identity,
                "model.error",
                safe_error_payload(error),
                terminal=True,
            )
            return f"Error generating summary: {error!s}"
        await self._append_trace(
            context,
            identity,
            "model.response",
            {"response": response},
            terminal=True,
        )
        return response.text.strip()

    async def _append_trace(
        self,
        context,
        identity: TraceIdentity,
        event_type: str,
        payload: dict[str, object],
        *,
        terminal: bool = False,
    ) -> None:
        if self._trace_writer is None:
            return
        try:
            written = await asyncio.to_thread(
                self._trace_writer.append,
                identity,
                event_type,
                payload,
                terminal=terminal,
            )
            if written:
                return
        except Exception:
            pass
        warning = getattr(context, "trace_warning", None)
        if warning is not None:
            try:
                warning("agent_trace_write_failed")
            except Exception:
                pass
