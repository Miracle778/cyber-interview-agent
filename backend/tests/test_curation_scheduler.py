from __future__ import annotations

import asyncio

import pytest

from app.review.curation_scheduler import curation_error_code, run_curation_wave


@pytest.mark.asyncio
async def test_wave_limits_active_workers_to_three() -> None:
    active = 0
    peak = 0
    first_wave_started = asyncio.Event()
    release = asyncio.Event()

    async def worker(_item_id: str) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 3:
            first_wave_started.set()
        try:
            await release.wait()
        finally:
            active -= 1

    task = asyncio.create_task(
        run_curation_wave(
            tuple(f"w-{index}" for index in range(6)),
            limit=3,
            worker=worker,
        )
    )
    await asyncio.wait_for(first_wave_started.wait(), timeout=1)
    assert peak == 3
    release.set()

    result = await asyncio.wait_for(task, timeout=1)

    assert result.completed_ids == tuple(f"w-{index}" for index in range(6))
    assert result.failed == ()
    assert peak == 3


@pytest.mark.asyncio
async def test_wave_preserves_input_order_when_completion_is_reversed() -> None:
    completed: list[str] = []

    async def worker(item_id: str) -> None:
        await asyncio.sleep((4 - int(item_id[-1])) * 0.002)
        completed.append(item_id)

    result = await run_curation_wave(
        tuple(f"w-{index}" for index in range(4)),
        limit=3,
        worker=worker,
    )

    assert completed != [f"w-{index}" for index in range(4)]
    assert result.completed_ids == tuple(f"w-{index}" for index in range(4))
    assert result.failed == ()


@pytest.mark.asyncio
async def test_wave_waits_for_sibling_successes_after_one_worker_fails() -> None:
    committed: list[str] = []

    class RateLimitedError(RuntimeError):
        code = "rate_limited"

    async def worker(item_id: str) -> None:
        if item_id == "w-1":
            raise RateLimitedError("provider response body must stay private")
        await asyncio.sleep(0.005)
        committed.append(item_id)

    result = await run_curation_wave(
        ("w-0", "w-1", "w-2"), limit=3, worker=worker
    )

    assert committed == ["w-0", "w-2"]
    assert result.completed_ids == ("w-0", "w-2")
    assert result.failed == (("w-1", "rate_limited"),)
    assert "provider" not in repr(result)


@pytest.mark.asyncio
async def test_outer_cancellation_waits_for_started_worker_cleanup() -> None:
    active = 0
    peak = 0
    started = asyncio.Event()
    stopped: list[str] = []

    async def worker(item_id: str) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1
            stopped.append(item_id)

    task = asyncio.create_task(
        run_curation_wave(("w-0", "w-1", "w-2"), limit=2, worker=worker)
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert peak == 2
    assert active == 0
    assert sorted(stopped) == ["w-0", "w-1"]


@pytest.mark.asyncio
async def test_wave_rejects_invalid_limits_without_starting_work() -> None:
    calls = 0

    async def worker(_item_id: str) -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(ValueError, match="limit"):
        await run_curation_wave(("w-0",), limit=0, worker=worker)

    assert calls == 0


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (type("RateLimit", (RuntimeError,), {"status_code": 429})("private"), "rate_limited"),
        (type("Server", (RuntimeError,), {"status_code": 503})("private"), "provider_server_error"),
        (type("Overloaded", (RuntimeError,), {"code": "overloaded_error"})("private"), "rate_limited"),
        (ConnectionError("private endpoint"), "network_error"),
    ],
)
def test_transport_failures_normalize_without_provider_body(
    error: BaseException, expected: str
) -> None:
    assert curation_error_code(error) == expected
    assert "private" not in curation_error_code(error)
