"""Health endpoints: a DB-only liveness probe and a DB + broker readiness probe.

``/health/live`` (liveness) verifies the process is up and the database is reachable.
``/health`` (readiness) additionally checks task-broker connectivity, so Kubernetes only
routes work to a replica that can actually accept and dispatch async ingest/detect/apply
tasks (redact-api#8).
"""

import asyncio
import logging
import time

import aio_pika
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, OperationalError

from redact_api.core.config import settings
from redact_api.core.logging import get_logging_context
from redact_api.db.session import SessionDep

logger = logging.getLogger(__name__)
router = APIRouter()
HEALTH_DB_TIMEOUT_SECONDS = 2.0
HEALTH_BROKER_TIMEOUT_SECONDS = 2.0


async def _check_database(session: SessionDep) -> None:
    """Run a short, timeout-bounded ``SELECT 1``; raise 503 on any DB failure."""
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


async def _check_broker() -> None:
    """Open and immediately close an AMQP connection to verify broker reachability."""
    context = get_logging_context()
    try:
        connection = await aio_pika.connect(settings.rabbitmq_url, timeout=HEALTH_BROKER_TIMEOUT_SECONDS)
        await connection.close()
    except Exception as exc:
        broker_error_msg = "Broker unavailable"
        logger.warning("health_check_broker_error", extra={**context, "error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=broker_error_msg,
        ) from exc


@router.get("/health/live", tags=["health"])
async def health_live(session: SessionDep) -> dict[str, str]:
    """Liveness probe: the process is up and the database is reachable.

    Returns:
        Status dict indicating service liveness

    Raises:
        HTTPException: 503 if the database is unreachable or times out
    """
    await _check_database(session)
    return {"status": "ok"}


@router.get("/health", tags=["health"])
async def health(session: SessionDep) -> dict[str, str]:
    """Readiness probe: the database and the task broker are both reachable.

    Extends the liveness database check with an AMQP broker-connectivity check, so a replica
    that cannot reach RabbitMQ (and therefore cannot dispatch async work) is marked not-ready.

    Returns:
        Status dict indicating service readiness

    Raises:
        HTTPException: 503 if the database or the task broker is unreachable
    """
    await _check_database(session)
    await _check_broker()
    return {"status": "ok"}
