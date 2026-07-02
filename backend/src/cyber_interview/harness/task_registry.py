import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class TaskRegistry:
    """Own background task references, exception boundary, and shutdown."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self.on_failure: Callable[[str, BaseException], Awaitable[None]] | None = None

    def create(self, run_id: str, coro: Awaitable) -> asyncio.Task:
        task = asyncio.create_task(self._wrap(run_id, coro))
        self._tasks[run_id] = task
        return task

    async def _wrap(self, run_id: str, coro: Awaitable) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            logger.exception("run %s failed", run_id)
            if self.on_failure is not None:
                try:
                    await self.on_failure(run_id, exc)
                except Exception:
                    logger.exception("on_failure hook errored for run %s", run_id)
        finally:
            self._tasks.pop(run_id, None)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()

    async def cancel_all(self) -> None:
        await self.shutdown()
