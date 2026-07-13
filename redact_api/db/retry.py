"""Database retry decorators for handling transient failures.

This module provides retry decorators for database operations that may
experience transient failures (connection drops, deadlocks, etc.).

Usage:
    from redact_api.db.retry import db_retry

    @db_retry
    async def create_user(session: AsyncSession, user: User) -> User:
        session.add(user)
        await session.commit()
        return user

For custom retry behavior, use the decorator factory:

    from redact_api.db.retry import create_db_retry

    custom_retry = create_db_retry(max_attempts=5, max_wait=30)

    @custom_retry
    async def critical_operation(session: AsyncSession) -> None:
        ...

Retry behavior:
    - Retries on OperationalError (connection issues, deadlocks)
    - Exponential backoff: 1s, 2s, 4s... up to max_wait
    - Default: 3 attempts, max 10s wait between retries
    - Logs retry attempts for observability
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from sqlalchemy.exc import OperationalError
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from redact_api.core.logging import get_logging_context

LOGGER = logging.getLogger(__name__)

# Type variables for generic decorator
P = ParamSpec("P")
T = TypeVar("T")

# Default retry configuration
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_WAIT_MULTIPLIER = 1
DEFAULT_MIN_WAIT = 1
DEFAULT_MAX_WAIT = 10


def _log_retry_attempt(retry_state: RetryCallState) -> None:
    """Log retry attempts with structured context.

    Args:
        retry_state: Tenacity retry state containing attempt info
    """
    base_context = get_logging_context()
    wait_seconds = getattr(retry_state.next_action, "sleep", 0) if retry_state.next_action else 0
    exception_type = type(retry_state.outcome.exception()).__name__ if retry_state.outcome else "unknown"

    extra = {
        **base_context,
        "attempt": retry_state.attempt_number,
        "wait_seconds": wait_seconds,
        "exception_type": exception_type,
    }
    LOGGER.warning("db_operation_retry", extra=extra)


def create_db_retry(
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    wait_multiplier: int = DEFAULT_WAIT_MULTIPLIER,
    min_wait: int = DEFAULT_MIN_WAIT,
    max_wait: int = DEFAULT_MAX_WAIT,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Create a database retry decorator with custom configuration.

    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
        wait_multiplier: Multiplier for exponential backoff (default: 1)
        min_wait: Minimum wait time in seconds (default: 1)
        max_wait: Maximum wait time in seconds (default: 10)

    Returns:
        Configured retry decorator

    Example:
        aggressive_retry = create_db_retry(max_attempts=5, max_wait=30)

        @aggressive_retry
        async def critical_write(session: AsyncSession) -> None:
            ...
    """
    return retry(
        retry=retry_if_exception_type(OperationalError),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=wait_multiplier, min=min_wait, max=max_wait),
        before_sleep=_log_retry_attempt,
        reraise=True,
    )


# Default retry decorator for database operations
db_retry: Callable[[Callable[P, T]], Callable[P, T]] = create_db_retry()
"""Default database retry decorator.

Retries on SQLAlchemy OperationalError with exponential backoff.

Configuration:
    - Max attempts: 3
    - Wait: exponential backoff (1s, 2s, 4s) capped at 10s
    - Retried exceptions: OperationalError (connection issues, deadlocks)

Example:
    @db_retry
    async def save_document(session: AsyncSession, doc: Document) -> Document:
        session.add(doc)
        await session.commit()
        return doc
"""
