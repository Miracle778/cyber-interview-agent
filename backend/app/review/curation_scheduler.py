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
    raw_code = getattr(error, "code", None)
    if isinstance(raw_code, Enum):
        raw_code = raw_code.value
    normalized_code: str | None = None
    if isinstance(raw_code, str):
        normalized_code = raw_code.strip().casefold().replace("-", "_")
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
        if normalized_code in aliases:
            mapped = aliases[normalized_code]
            if mapped == "rate_limited":
                return mapped

    status_code = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    if status_code is None:
        status_code = getattr(response, "status_code", None)
    class_names = {
        base.__name__.casefold() for base in type(error).__mro__
    }
    if (
        _has_retry_after(error, response)
        or status_code in {429, 529}
        or any("overload" in name for name in class_names)
    ):
        return "rate_limited"
    if isinstance(status_code, int) and status_code >= 500:
        return "provider_server_error"
    if isinstance(error, TimeoutError) or any(
        "timeout" in name for name in class_names
    ):
        return "provider_timeout"
    if isinstance(error, (ConnectionError, OSError)) or any(
        name in {"apiconnectionerror", "connecterror", "networkerror"}
        or "connectionerror" in name
        for name in class_names
    ):
        return "network_error"
    if normalized_code is not None:
        aliases = {
            "connection_error": "network_error",
            "network_error": "network_error",
            "timeout": "provider_timeout",
            "provider_timeout": "provider_timeout",
            "provider_error": "provider_error",
            "provider_server_error": "provider_server_error",
            "protocol_error": "protocol_error",
            "schema_validation_error": "schema_validation_error",
        }
        if normalized_code in aliases:
            return aliases[normalized_code]
    return "curation_work_item_failed"


def _has_retry_after(error: BaseException, response: object) -> bool:
    for owner in (error, response):
        headers = getattr(owner, "headers", None)
        if headers is None:
            continue
        try:
            if any(str(key).casefold() == "retry-after" for key in headers):
                return True
        except TypeError:
            continue
    return False


def is_curation_overload_error(error_code: str) -> bool:
    return error_code == "rate_limited"
