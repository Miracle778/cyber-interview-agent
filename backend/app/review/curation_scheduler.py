"""Bounded, failure-isolated scheduling for curation work-item waves."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class CurationWaveResult:
    completed_ids: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]


async def run_curation_wave(
    work_item_ids: tuple[str, ...],
    *,
    limit: int,
    worker: Callable[[str], Awaitable[None]],
) -> CurationWaveResult:
    """Run every item with bounded concurrency and deterministic aggregation."""
    if limit <= 0:
        raise ValueError("curation wave limit must be positive")
    semaphore = asyncio.Semaphore(limit)

    async def run_one(work_item_id: str) -> None:
        async with semaphore:
            await worker(work_item_id)

    tasks = tuple(
        asyncio.create_task(run_one(work_item_id), name=f"curation:{work_item_id}")
        for work_item_id in work_item_ids
    )
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    completed: list[str] = []
    failed: list[tuple[str, str]] = []
    cancellation: asyncio.CancelledError | None = None
    for work_item_id, result in zip(work_item_ids, results, strict=True):
        if isinstance(result, asyncio.CancelledError):
            cancellation = result
        elif isinstance(result, BaseException):
            failed.append((work_item_id, curation_error_code(result)))
        else:
            completed.append(work_item_id)
    if cancellation is not None:
        raise cancellation
    return CurationWaveResult(tuple(completed), tuple(failed))


def curation_error_code(error: BaseException) -> str:
    """Return a stable safe code without using Provider response text."""
    status_code = getattr(error, "status_code", None)
    if status_code == 429:
        return "rate_limited"
    if isinstance(status_code, int) and status_code >= 500:
        return "provider_server_error"
    if isinstance(error, TimeoutError):
        return "provider_timeout"
    if isinstance(error, (ConnectionError, OSError)):
        return "network_error"

    raw_code = getattr(error, "code", None)
    if isinstance(raw_code, Enum):
        raw_code = raw_code.value
    if isinstance(raw_code, str):
        normalized = raw_code.strip().casefold().replace("-", "_")
        aliases = {
            "429": "rate_limited",
            "overload": "rate_limited",
            "overload_error": "rate_limited",
            "overloaded": "rate_limited",
            "overloaded_error": "rate_limited",
            "provider_overloaded": "rate_limited",
            "rate_limit": "rate_limited",
            "rate_limited": "rate_limited",
            "connection_error": "network_error",
            "network_error": "network_error",
            "timeout": "provider_timeout",
            "provider_timeout": "provider_timeout",
            "provider_error": "provider_error",
            "provider_server_error": "provider_server_error",
            "protocol_error": "protocol_error",
            "schema_validation_error": "schema_validation_error",
        }
        if normalized in aliases:
            return aliases[normalized]
    return "curation_work_item_failed"


def is_curation_overload_error(error_code: str) -> bool:
    return error_code == "rate_limited"
