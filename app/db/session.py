from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.core.config import settings


class DatabaseSessionManager:
    def __init__(self) -> None:
        self.engine = create_async_engine(
            settings.database_url,
            future=True,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        session = self.session_factory()
        try:
            yield session
        finally:
            await session.close()

    async def create_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text(
                    """
                    ALTER TABLE IF EXISTS push_devices
                    ADD COLUMN IF NOT EXISTS sns_endpoint_arn TEXT,
                    ADD COLUMN IF NOT EXISTS sns_application_arn TEXT,
                    ADD COLUMN IF NOT EXISTS last_delivery_status VARCHAR(30),
                    ADD COLUMN IF NOT EXISTS last_error TEXT
                    """
                )
            )

    async def drop_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))


db_session = DatabaseSessionManager()
