import asyncio
from typing import Any

from app.runtime.checkpoints import RuntimeCheckpointer
from app.runtime.event_stream import EventStream
from app.runtime.graph_registry import GraphRegistry
from app.runtime.models import RunRecord
from app.runtime.repository import InvalidRunTransitionError, RuntimeRepository


class RunManager:
    def __init__(
        self,
        *,
        repository: RuntimeRepository,
        event_stream: EventStream,
        graph_registry: GraphRegistry,
        checkpointer: RuntimeCheckpointer,
    ) -> None:
        self._repository = repository
        self._event_stream = event_stream
        self._graph_registry = graph_registry
        self._checkpointer = checkpointer
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}

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
            session_id, input=input, model_bindings=model_bindings
        )
        text = input.get("text")
        if isinstance(text, str) and text.strip():
            self._repository.append_message(
                session_id, run_id=run.id, role="user", content=text
            )
        self._spawn(run.id, graph_input=input)
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
            run = self._repository.transition_run(
                run_id, expected=run.status, target="cancelled"
            )
            await self._event_stream.publish(
                run.session_id, run.id, "run.cancelled", {}
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
        run = self._repository.resume_run(run_id, expected="interrupted")
        self._spawn(run.id, graph_input=None)
        return run

    async def shutdown(self) -> None:
        for run_id in tuple(self._tasks):
            await self.cancel(run_id)

    def _spawn(self, run_id: str, *, graph_input: dict[str, Any] | None) -> None:
        task = asyncio.create_task(self._execute(run_id, graph_input=graph_input))
        self._tasks[run_id] = task

        def discard(completed: asyncio.Task[None]) -> None:
            if self._tasks.get(run_id) is completed:
                self._tasks.pop(run_id, None)

        task.add_done_callback(discard)

    async def _execute(
        self, run_id: str, *, graph_input: dict[str, Any] | None
    ) -> None:
        run = self._repository.get_run(run_id)
        lock = self._session_locks.setdefault(run.session_id, asyncio.Lock())
        try:
            async with lock:
                run = self._repository.transition_run(
                    run.id, expected="queued", target="running"
                )
                await self._event_stream.publish(
                    run.session_id, run.id, "run.started", {}
                )
                session = self._repository.get_session(run.session_id)
                definition = self._graph_registry.get(
                    session.graph_id, session.graph_version
                )
                async with self._checkpointer.open() as checkpointer:
                    graph = definition.factory(checkpointer)
                    result = await graph.ainvoke(
                        graph_input,
                        {"configurable": {"thread_id": run.session_id}},
                    )

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
                    error_message=str(error),
                )
                await self._event_stream.publish(
                    failed.session_id,
                    failed.id,
                    "run.failed",
                    {"code": "runtime_error", "message": str(error)},
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
