"""Health endpoint with a short DB connectivity check."""

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, OperationalError

from redact_api.core.logging import get_logging_context
from redact_api.db.session import SessionDep

logger = logging.getLogger(__name__)
router = APIRouter()
HEALTH_DB_TIMEOUT_SECONDS = 2.0


@router.get("/health", tags=["health"])
async def health(session: SessionDep) -> dict[str, str]:
    """Health check endpoint with database connectivity verification.

    Performs a lightweight database query with timeout to verify the service
    is operational and can communicate with the database.

    Returns:
        Status dict indicating service health

    Raises:
        HTTPException: 503 if database is unreachable or times out
    """
    context = get_logging_context()
    start_time = time.perf_counter()

    try:
        await asyncio.wait_for(
            session.execute(text("SELECT 1")),
            timeout=HEALTH_DB_TIMEOUT_SECONDS,
        )
        duration_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "health_check_success",
            extra={
                **context,
                "status": "ok",
                "db_response_time_ms": round(duration_ms, 2),
            },
        )
    except TimeoutError as exc:
        # Async operation timeout - database is slow or unresponsive
        # Note: asyncio.TimeoutError is aliased to TimeoutError in Python 3.11+
        timeout_msg = "Database timeout"
        logger.warning(
            "health_check_timeout",
            extra={
                **context,
                "timeout_seconds": HEALTH_DB_TIMEOUT_SECONDS,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=timeout_msg,
        ) from exc
    except OperationalError as exc:
        # Database connection issues (network, authentication, etc.)
        db_error_msg = "Database unavailable"
        logger.exception(
            "health_check_operational_error",
            extra=context,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=db_error_msg,
        ) from exc
    except DatabaseError as exc:
        # Generic database errors (query failures, integrity issues)
        db_error_msg = "Database error"
        logger.exception(
            "health_check_database_error",
            extra=context,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=db_error_msg,
        ) from exc
    return {"status": "ok"}
