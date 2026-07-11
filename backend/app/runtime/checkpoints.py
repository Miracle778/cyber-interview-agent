from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.db.runtime_database import runtime_database_path


class RuntimeCheckpointer:
    def __init__(self, workspace_root: Path) -> None:
        self._database_path = runtime_database_path(workspace_root)

    @asynccontextmanager
    async def open(self) -> AsyncIterator[AsyncSqliteSaver]:
        connection = await aiosqlite.connect(self._database_path)
        try:
            await connection.execute("PRAGMA busy_timeout = 5000")
            saver = AsyncSqliteSaver(connection)
            await saver.setup()
            yield saver
        finally:
            await connection.close()

    async def has_checkpoint(self, session_id: str) -> bool:
        async with self.open() as saver:
            checkpoint = await saver.aget_tuple(
                {"configurable": {"thread_id": session_id}}
            )
        return checkpoint is not None
