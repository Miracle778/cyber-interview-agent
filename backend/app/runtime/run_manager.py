import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langgraph.types import Command

from app.hitl.models import CreatePendingAction, PendingActionRecord
from app.runtime.checkpoints import RuntimeCheckpointer
from app.runtime.event_stream import EventStream
from app.runtime.graph_build_context import GraphBuildContext
from app.runtime.graph_registry import GraphRegistry
from app.runtime.models import RunRecord
from app.runtime.repository import InvalidRunTransitionError, RuntimeRepository
from app.tools.audit import ToolAuditRepository
from app.tools.context import ToolExecutionContext
from app.tools.executor import BoundToolInvoker
from app.tools.registry import ToolRegistry


class RunManager:
    def __init__(
        self,
        *,
        repository: RuntimeRepository,
        event_stream: EventStream,
        graph_registry: GraphRegistry,
        checkpointer: RuntimeCheckpointer,
        workspace_root: Path,
        tool_registry: ToolRegistry,
        audit_repository: ToolAuditRepository,
        request_action: Callable[
            [CreatePendingAction], Awaitable[PendingActionRecord]
        ] | None = None,
        cancel_pending_action: Callable[
            [str], Awaitable[PendingActionRecord | None]
        ] | None = None,
    ) -> None:
        self._repository = repository
        self._event_stream = event_stream
        self._graph_registry = graph_registry
        self._checkpointer = checkpointer
        self._workspace_root = workspace_root
        self._tool_registry = tool_registry
        self._audit_repository = audit_repository
        self._request_action = request_action or self._unavailable_action_request
        self._cancel_pending_action = (
            cancel_pending_action or self._no_pending_action
        )
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._is_shutting_down = False

    @staticmethod
    async def _unavailable_action_request(
        _request: CreatePendingAction,
    ) -> PendingActionRecord:
        raise RuntimeError("HITL action requests are not configured")

    @staticmethod
    async def _no_pending_action(_run_id: str) -> PendingActionRecord | None:
        return None

    async def start(
        self,
        session_id: str,
        *,
        input: dict[str, Any],
        model_bindings: dict[str, str],
    ) -> RunRecord:
        session = self._repository.get_session(session_id)
        self._graph_registry.get(session.graph_id, session.graph_version)
        run = self._repository.create_run(
            session_id,
            input=input,
            model_bindings=model_bindings,
            initial_status="running",
        )
        try:
            text = input.get("text")
            if isinstance(text, str) and text.strip():
                self._repository.append_message(
                    session_id, run_id=run.id, role="user", content=text
                )
            await self._event_stream.publish(
                run.session_id, run.id, "run.started", {}
            )
            self._spawn(run.id, graph_input=input)
        except BaseException:
            self._interrupt_unspawned(run.id)
            raise
        return run

    async def wait(self, run_id: str) -> RunRecord:
        task = self._tasks.get(run_id)
        if task is not None:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
        return self._repository.get_run(run_id)

    async def cancel(self, run_id: str) -> RunRecord:
        run = self._repository.get_run(run_id)
        if run.status not in {"queued", "running", "waiting_for_approval"}:
            return run

        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        run = self._repository.get_run(run_id)
        if run.status in {"queued", "running", "waiting_for_approval"}:
            cancelled_action = await self._cancel_pending_action(run.id)
            run = self._repository.transition_run(
                run_id, expected=run.status, target="cancelled"
            )
            await self._event_stream.publish(
                run.session_id, run.id, "run.cancelled", {}
            )
            if cancelled_action is not None:
                await self._event_stream.publish(
                    run.session_id,
                    run.id,
                    "hitl.resolved",
                    {
                        "actionId": cancelled_action.id,
                        "status": "cancelled",
                        "version": cancelled_action.version,
                    },
                )
        return run

    async def recover_interrupted_runs(self) -> tuple[str, ...]:
        run_ids = self._repository.interrupt_running_runs()
        for run_id in run_ids:
            run = self._repository.get_run(run_id)
            await self._event_stream.publish(
                run.session_id, run.id, "run.interrupted", {}
            )
        return run_ids

    async def resume(self, run_id: str) -> RunRecord:
        interrupted = self._repository.get_run(run_id)
        graph_input = (
            None
            if await self._checkpointer.has_checkpoint(interrupted.session_id)
            else interrupted.input
        )
        run = self._repository.resume_run(
            run_id, expected="interrupted", target="running"
        )
        try:
            await self._event_stream.publish(
                run.session_id, run.id, "run.started", {}
            )
            self._spawn(run.id, graph_input=graph_input)
        except BaseException:
            self._interrupt_unspawned(run.id)
            raise
        return run

    async def resume_approval(
        self,
        run_id: str,
        decision: dict[str, Any],
        _receipt_id: str,
    ) -> None:
        current = self._repository.get_run(run_id)
        if current.status in {"completed", "cancelled"}:
            return
        if current.status not in {"waiting_for_approval", "interrupted"}:
            raise InvalidRunTransitionError(
                f"run {run_id!r} cannot resume approval from {current.status!r}"
            )
        run = self._repository.resume_run(
            run_id, expected=current.status, target="running"
        )
        try:
            await self._event_stream.publish(
                run.session_id,
                run.id,
                "run.started",
                {"resumeAttempt": run.resume_count},
            )
            self._spawn(run.id, graph_input=Command(resume=decision))
        except BaseException:
            self._interrupt_unspawned(run.id)
            raise

    async def shutdown(self) -> None:
        self._is_shutting_down = True
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.recover_interrupted_runs()

    def _spawn(self, run_id: str, *, graph_input: object | None) -> None:
        task = asyncio.create_task(self._execute(run_id, graph_input=graph_input))
        self._tasks[run_id] = task

        def discard(completed: asyncio.Task[None]) -> None:
            if self._tasks.get(run_id) is completed:
                self._tasks.pop(run_id, None)

        task.add_done_callback(discard)

    def _interrupt_unspawned(self, run_id: str) -> None:
        run = self._repository.get_run(run_id)
        if run.status == "running":
            self._repository.transition_run(
                run.id, expected="running", target="interrupted"
            )

    async def _execute(
        self, run_id: str, *, graph_input: object | None
    ) -> None:
        run = self._repository.get_run(run_id)
        lock = self._session_locks.setdefault(run.session_id, asyncio.Lock())
        try:
            async with lock:
                session = self._repository.get_session(run.session_id)
                definition = self._graph_registry.get(
                    session.graph_id, session.graph_version
                )
                tool_context = ToolExecutionContext(
                    workspace_id=session.workspace_id,
                    workspace_root=self._workspace_root,
                    session_id=session.id,
                    run_id=run.id,
                    graph_id=definition.graph_id,
                    graph_version=definition.graph_version,
                    allowed_tools=definition.allowed_tools,
                    allowed_scopes=definition.allowed_scopes,
                )
                invoker = BoundToolInvoker(
                    context=tool_context,
                    registry=self._tool_registry,
                    audit_repository=self._audit_repository,
                    event_stream=self._event_stream,
                )
                requested_action_ids: set[str] = set()

                async def request_action(
                    *,
                    action_type: str,
                    payload: dict[str, Any],
                    preview: dict[str, Any],
                    editable_fields: tuple[str, ...],
                    idempotency_key: str,
                ) -> PendingActionRecord:
                    action = await self._request_action(
                        CreatePendingAction(
                            workspace_id=session.workspace_id,
                            session_id=session.id,
                            run_id=run.id,
                            action_type=action_type,
                            payload=payload,
                            preview=preview,
                            editable_fields=editable_fields,
                            idempotency_key=f"{run.id}:{idempotency_key}",
                        )
                    )
                    requested_action_ids.add(action.id)
                    return action

                async with self._checkpointer.open() as checkpointer:
                    graph = definition.factory(
                        GraphBuildContext(
                            checkpointer=checkpointer,
                            invoke_tool=invoker.invoke_tool,
                            request_action=request_action,
                        )
                    )
                    result = await graph.ainvoke(
                        graph_input,
                        {"configurable": {"thread_id": run.session_id}},
                    )

                interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
                if interrupts:
                    interrupt_value = getattr(interrupts[0], "value", None)
                    action_id = (
                        interrupt_value.get("actionId")
                        if isinstance(interrupt_value, dict)
                        else None
                    )
                    if not isinstance(action_id, str):
                        raise RuntimeError("HITL interrupt is missing actionId")
                    if action_id not in requested_action_ids:
                        raise RuntimeError(
                            "HITL interrupt action was not created by this run"
                        )
                    waiting = self._repository.transition_run(
                        run.id,
                        expected="running",
                        target="waiting_for_approval",
                    )
                    await self._event_stream.publish(
                        waiting.session_id,
                        waiting.id,
                        "hitl.required",
                        {"actionId": action_id},
                    )
                    return

                response = result.get("response") if isinstance(result, dict) else None
                if isinstance(response, str) and response:
                    message = self._repository.append_message(
                        run.session_id,
                        run_id=run.id,
                        role="assistant",
                        content=response,
                    )
                    await self._event_stream.publish(
                        run.session_id,
                        run.id,
                        "message.completed",
                        {"messageId": message.id, "content": response},
                    )
                self._repository.transition_run(
                    run.id, expected="running", target="completed"
                )
                await self._event_stream.publish(
                    run.session_id, run.id, "run.completed", {}
                )
        except asyncio.CancelledError:
            if not self._is_shutting_down:
                await self._mark_cancelled(run_id)
            raise
        except Exception as error:
            current = self._repository.get_run(run_id)
            if current.status in {"queued", "running"}:
                failed = self._repository.transition_run(
                    run_id,
                    expected=current.status,
                    target="failed",
                    error_code="runtime_error",
                    error_message="Agent 运行失败",
                )
                await self._event_stream.publish(
                    failed.session_id,
                    failed.id,
                    "run.failed",
                    {"code": "runtime_error", "message": "Agent 运行失败"},
                )

    async def _mark_cancelled(self, run_id: str) -> None:
        current = self._repository.get_run(run_id)
        if current.status not in {"queued", "running", "waiting_for_approval"}:
            return
        try:
            cancelled = self._repository.transition_run(
                run_id, expected=current.status, target="cancelled"
            )
        except InvalidRunTransitionError:
            return
        await self._event_stream.publish(
            cancelled.session_id, cancelled.id, "run.cancelled", {}
        )
