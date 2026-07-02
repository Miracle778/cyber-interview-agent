import asyncio

import pytest

from cyber_interview.harness.task_registry import TaskRegistry


@pytest.mark.asyncio
async def test_task_runs_without_subscriber():
    seen = asyncio.Event()
    registry = TaskRegistry()

    async def work():
        await asyncio.sleep(0.01)
        seen.set()

    registry.create("run-1", work())
    await asyncio.sleep(0.05)
    assert seen.is_set()
    assert "run-1" not in registry._tasks
    await registry.shutdown()


@pytest.mark.asyncio
async def test_uncaught_exception_does_not_leave_running(monkeypatch):
    registry = TaskRegistry()
    failed_calls = []

    async def on_fail(run_id, exc):
        failed_calls.append((run_id, type(exc)))

    registry.on_failure = on_fail

    async def boom():
        raise ValueError("boom")

    registry.create("run-2", boom())
    await asyncio.sleep(0.05)
    assert failed_calls and failed_calls[0][0] == "run-2"
    await registry.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_active_tasks():
    registry = TaskRegistry()
    cancelled = asyncio.Event()

    async def long():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    registry.create("run-3", long())
    await asyncio.sleep(0.01)
    await registry.shutdown()
    assert cancelled.is_set()
