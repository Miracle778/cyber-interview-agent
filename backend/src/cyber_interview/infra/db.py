from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cyber_interview.settings import Settings


def engine_from_settings(settings: Settings) -> AsyncEngine:
    db_path = settings.data_dir / "career.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)


def session_factory_from_settings(settings: Settings) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine_from_settings(settings), expire_on_commit=False)
