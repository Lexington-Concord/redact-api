"""Async SQLAlchemy engine and session dependency for the API."""

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from redact_api.core.config import settings
from redact_api.core.logging import get_logging_context

LOGGER = logging.getLogger(__name__)


class PoolConfig(BaseModel, frozen=True):
    """Database connection pool configuration.

    This model encapsulates all pool-related settings for SQLAlchemy's
    async engine. Using a Pydantic model ensures validation and provides
    a clean API for configuring database connections.

    Attributes:
        size: Number of connections to keep in pool
        max_overflow: Max connections beyond pool_size
        timeout: Seconds to wait for available connection
        recycle: Seconds before recycling connection (-1 to disable)
        pre_ping: Test connection validity before use

    Example:
        # Default configuration
        config = PoolConfig()

        # Custom configuration for high-traffic service
        config = PoolConfig(size=20, max_overflow=40, timeout=10.0)
    """

    size: int = Field(default=5, ge=1, le=100, description="Pool size")
    max_overflow: int = Field(default=10, ge=0, le=100, description="Max overflow")
    timeout: float = Field(default=30.0, ge=1.0, description="Connection timeout")
    recycle: int = Field(default=1800, ge=-1, description="Connection recycle time")
    pre_ping: bool = Field(default=True, description="Enable pre-ping health check")


# Default pool configuration
DEFAULT_POOL_CONFIG = PoolConfig()


def create_db_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool: PoolConfig | None = None,
) -> AsyncEngine:
    """Factory function to create database engine.

    Use this function in application lifespan to create the engine
    and store it in app.state for pytest-xdist compatibility.

    Args:
        database_url: Database connection URL
        echo: Echo SQL statements to logs
        pool: Connection pool configuration (uses defaults if not specified)

    Returns:
        Configured async SQLAlchemy engine

    Example:
        # With defaults
        engine = create_db_engine("postgresql+asyncpg://...")

        # With custom pool config
        pool_config = PoolConfig(size=10, max_overflow=20)
        engine = create_db_engine("postgresql+asyncpg://...", pool=pool_config)
    """
    pool_config = pool or DEFAULT_POOL_CONFIG
    return create_async_engine(
        database_url,
        echo=echo,
        pool_size=pool_config.size,
        max_overflow=pool_config.max_overflow,
        pool_timeout=pool_config.timeout,
        pool_recycle=pool_config.recycle,
        pool_pre_ping=pool_config.pre_ping,
    )


def create_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Factory function to create session maker.

    Use this function in application lifespan to create the session maker
    and store it in app.state for pytest-xdist compatibility.

    Args:
        engine: Async SQLAlchemy engine to bind sessions to

    Returns:
        Configured async session maker
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


# Global engine and session maker for backward compatibility.
# These are used by:
# - core/activity_logging.py (fire-and-forget logging without request context)
# - tests/conftest.py (test fixtures update these to point to worker database)
#
# For new code, prefer using app.state.engine and app.state.async_session_maker
# via the get_session() dependency or request.app.state in middleware.
_default_pool = PoolConfig(
    size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    timeout=settings.db_pool_timeout,
    recycle=settings.db_pool_recycle,
    pre_ping=settings.db_pool_pre_ping,
)
engine = create_db_engine(
    settings.database_url,
    echo=settings.sqlalchemy_echo,
    pool=_default_pool,
)
async_session_maker: async_sessionmaker[AsyncSession] = create_session_maker(engine)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Create async database session for request scope.

    Session lifecycle:
    1. Session created from pool
    2. Yielded to request handler
    3. Committed on success OR rolled back on exception
    4. Session closed and returned to pool

    The session dependency handles rollback automatically on exceptions.
    Callers are responsible for explicit commits.

    For pytest-xdist compatibility, test fixtures update the global
    async_session_maker to use the worker-specific database. This allows
    the same code path to work both in production and tests without
    requiring request access in the dependency.

    Yields:
        AsyncSession for database operations
    """
    context = get_logging_context()
    LOGGER.debug("session_created", extra=context)

    async with async_session_maker() as session:
        try:
            yield session
            LOGGER.debug("session_completed", extra=context)
        except Exception:
            LOGGER.warning("session_rollback", extra=context, exc_info=True)
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def init_db(db_engine: AsyncEngine | None = None) -> None:
    """Test-only helper; production migrations should use Alembic.

    Args:
        db_engine: Optional engine to use. Defaults to global engine for backward compatibility.
    """
    target_engine = db_engine if db_engine is not None else engine
    async with target_engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
