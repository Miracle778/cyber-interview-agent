from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from langgraph.types import Command

from app.agents.context import AgentContext
from app.application.event_projector import AgentEventProjector
from app.application.session_service import (
    ExecutionRecord,
    ProductEventStream,
    ProductRepository,
    SessionRecord,
)
from app.hitl.models import CreatePendingAction, PendingActionRecord
from app.infrastructure.checkpoints import AgentCheckpointer
from app.knowledge.drafts import CreateDraftCommand, KnowledgeDraftRecord


logger = logging.getLogger(__name__)


class GraphFactory(Protocol):
    def __call__(self, kind: str, **dependencies): ...


class AgentExecutionService:
    def __init__(
        self,
        *,
        workspace_id: str,
        workspace_root: Path,
        repository: ProductRepository,
        events: ProductEventStream,
        graph_factory: GraphFactory,
        model_bindings: Callable[[], Mapping[str, str]],
        create_action: Callable[[CreatePendingAction], Awaitable[PendingActionRecord]],
        create_draft: Callable[[CreateDraftCommand], Awaitable[KnowledgeDraftRecord]],
        mark_draft_review_pending: Callable[..., Awaitable[KnowledgeDraftRecord]],
    ) -> None:
        self._workspace_id = workspace_id
        self._workspace_root = workspace_root
        self._repository = repository
        self._events = events
        self._graph_factory = graph_factory
        self._model_bindings = model_bindings
        self._create_action = create_action
        self._create_draft = create_draft
        self._mark_draft_review_pending = mark_draft_review_pending
        self._checkpointer = AgentCheckpointer(workspace_root)
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def start(
        self, session: SessionRecord, *, input: dict[str, Any]
    ) -> ExecutionRecord:
        bindings = dict(self._model_bindings())
        execution = self._repository.create_execution(
            session.id,
            input=input,
            model_bindings=bindings,
        )
        self._repository.append_message(
            session.id,
            execution_id=execution.id,
            role="user",
            content=_user_content(input),
        )
        await self._events.publish(
            session.id,
            execution.id,
            "execution.started",
            {"executionId": execution.id},
        )
        self._spawn(execution.id, graph_input=input)
        return execution

    async def resume_approval(
        self, execution_id: str, decision: dict[str, Any], _receipt_id: str
    ) -> None:
        execution = self._repository.transition_execution(
            execution_id,
            expected=("waiting_for_approval", "interrupted"),
            target="running",
            increment_resume=True,
        )
        await self._events.publish(
            execution.session_id,
            execution.id,
            "execution.started",
            {"executionId": execution.id, "resumed": True},
        )
        self._spawn(execution.id, graph_input=Command(resume=decision))

    async def cancel(self, execution_id: str) -> ExecutionRecord:
        current = self._repository.get_execution(execution_id)
        if current.status in {"completed", "failed", "cancelled"}:
            return current
        task = self._tasks.get(execution_id)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        cancelled = self._repository.transition_execution(
            execution_id,
            expected=("running", "waiting_for_approval", "interrupted"),
            target="cancelled",
        )
        await self._events.publish(
            cancelled.session_id,
            cancelled.id,
            "execution.cancelled",
            {"executionId": cancelled.id},
        )
        return cancelled

    async def wait(self, execution_id: str) -> ExecutionRecord:
        task = self._tasks.get(execution_id)
        if task is not None:
            await task
        return self._repository.get_execution(execution_id)

    async def close(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._repository.interrupt_running()
        self._tasks.clear()

    def recover(self) -> tuple[str, ...]:
        return self._repository.interrupt_running()

    def _spawn(self, execution_id: str, *, graph_input: object) -> None:
        task = asyncio.create_task(self._execute(execution_id, graph_input))
        self._tasks[execution_id] = task

        def discard(completed: asyncio.Task[None]) -> None:
            if self._tasks.get(execution_id) is completed:
                self._tasks.pop(execution_id, None)

        task.add_done_callback(discard)

    async def _execute(self, execution_id: str, graph_input: object) -> None:
        execution = self._repository.get_execution(execution_id)
        session = self._repository.get_session(execution.session_id)
        context = AgentContext(
            workspace_id=self._workspace_id,
            workspace_root=self._workspace_root,
            session_id=session.id,
            run_id=execution.id,
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
        )

        async def create_action(**values):
            return await self._create_action(
                CreatePendingAction(
                    workspace_id=self._workspace_id,
                    session_id=session.id,
                    run_id=execution.id,
                    action_type=values["action_type"],
                    payload=values["payload"],
                    preview=values["preview"],
                    editable_fields=tuple(values.get("editable_fields", ())),
                    idempotency_key=values["idempotency_key"],
                )
            )

        async def create_draft(**values):
            draft = await self._create_draft(
                CreateDraftCommand(
                    domain="review",
                    document_type="session_report",
                    title=values["title"],
                    markdown=values["markdown"],
                    source_refs=tuple(values.get("source_refs", ())),
                    relation_refs=tuple(values.get("relation_refs", ())),
                    session_id=session.id,
                    run_id=execution.id,
                    agent_type=session.kind,
                )
            )
            return await self._mark_draft_review_pending(
                draft.id,
                expected_version=draft.version,
                expected_hash=draft.content_hash,
            )

        final_state: dict[str, Any] = {}
        interrupted = False
        projected_text = False
        projector = AgentEventProjector()
        try:
            async with self._checkpointer.open() as saver:
                graph = self._graph_factory(
                    session.kind,
                    model_bindings=dict(self._model_bindings()),
                    checkpointer=saver,
                    context=context,
                    create_action=create_action,
                    create_draft=create_draft,
                )
                async for part in graph.astream(
                    graph_input,
                    config={"configurable": {"thread_id": session.id}},
                    context=context,
                    stream_mode=["values", "messages", "custom", "tasks"],
                    version="v2",
                ):
                    if part.get("type") == "values":
                        data = part.get("data")
                        if isinstance(data, dict):
                            final_state = data
                        if part.get("interrupts"):
                            interrupted = True
                    for event in projector.project(part):
                        if event.type == "assistant.delta":
                            projected_text = True
                        await self._events.publish(
                            session.id,
                            execution.id,
                            event.type,
                            event.payload,
                        )
            if interrupted:
                self._repository.transition_execution(
                    execution.id,
                    expected=("running",),
                    target="waiting_for_approval",
                )
                await self._events.publish(
                    session.id,
                    execution.id,
                    "execution.interrupted",
                    {"executionId": execution.id},
                )
                return

            response = _assistant_content(final_state)
            if response:
                self._repository.append_message(
                    session.id,
                    execution_id=execution.id,
                    role="assistant",
                    content=response,
                )
                if not projected_text:
                    await self._events.publish(
                        session.id,
                        execution.id,
                        "assistant.delta",
                        {"text": response},
                    )
            self._repository.transition_execution(
                execution.id,
                expected=("running",),
                target="completed",
            )
            await self._events.publish(
                session.id,
                execution.id,
                "execution.completed",
                {"executionId": execution.id},
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception(
                "agent execution failed",
                extra={
                    "execution_id": execution.id,
                    "session_id": session.id,
                    "error_code": str(
                        getattr(error, "code", "agent_execution_failed")
                    ),
                },
            )
            try:
                current = self._repository.get_execution(execution.id)
                if current.status == "running":
                    self._repository.transition_execution(
                        execution.id,
                        expected=("running",),
                        target="failed",
                        error_code=str(
                            getattr(error, "code", "agent_execution_failed")
                        ),
                        error_message="Agent 执行失败",
                    )
                    await self._events.publish(
                        session.id,
                        execution.id,
                        "execution.failed",
                        {
                            "code": str(
                                getattr(error, "code", "agent_execution_failed")
                            )
                        },
                    )
            except Exception:
                logger.exception(
                    "failed to persist agent execution failure",
                    extra={"execution_id": execution.id},
                )


def _user_content(input: dict[str, Any]) -> str:
    for key in ("userAnswer", "user_answer", "text"):
        value = input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(input, ensure_ascii=False, sort_keys=True)


def _assistant_content(state: dict[str, Any]) -> str:
    for key in ("response", "report_markdown"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
