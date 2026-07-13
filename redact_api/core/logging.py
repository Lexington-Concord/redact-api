"""Structured logging with user and organization context for audit trails.

This module provides context-aware logging that integrates with ECS (Elastic
Common Schema) logging format. It uses Python's contextvars to maintain request
context across async operations, allowing services to automatically include
user_id, org_id, and request_id in all log entries.

Usage:

    # In middleware (automatically configured in main.py)
    from redact_api.core.logging import LoggingMiddleware
    app.add_middleware(LoggingMiddleware)

    # In services
    import logging
    from redact_api.core.logging import get_logging_context

    logger = logging.getLogger(__name__)

    async def create_organization(session, payload):
        context = get_logging_context()
        logger.info(
            "creating_organization",
            extra={
                "organization_name": payload.name,
                "user_id": context.get("user_id"),
                "org_id": context.get("org_id"),
                "request_id": context.get("request_id"),
            }
        )
        # ... business logic ...
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from redact_api.core.config import settings

LOGGER = logging.getLogger(__name__)

# Constants
DEFAULT_REQUEST_ID_HEADER = "x-request-id"

# ContextVars for request-scoped logging context
# These survive async context switches and are available throughout the
# request lifecycle
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
_org_id_var: ContextVar[str | None] = ContextVar("org_id", default=None)


def set_request_id(request_id: str) -> None:
    """Set request ID in context for current async task.

    Args:
        request_id: Unique identifier for the request (UUID or correlation ID)
    """
    _request_id_var.set(request_id)


def get_request_id() -> str | None:
    """Get request ID from context.

    Returns:
        Request ID if set, None otherwise
    """
    return _request_id_var.get()


def set_user_context(user_id: str, org_id: str | None = None) -> None:
    """Set user and organization context for current request.

    Args:
        user_id: User ID from authenticated user
        org_id: Organization ID from authenticated user (optional)
    """
    _user_id_var.set(user_id)
    if org_id:
        _org_id_var.set(org_id)


def get_user_id() -> str | None:
    """Get user ID from context.

    Returns:
        User ID if set, None otherwise
    """
    return _user_id_var.get()


def get_org_id() -> str | None:
    """Get organization ID from context.

    Returns:
        Organization ID if set, None otherwise
    """
    return _org_id_var.get()


def get_logging_context() -> dict[str, str | None]:
    """Get all logging context as dict for structured logging.

    Returns:
        Dict with request_id, user_id, org_id (values may be None)

    Example:
        context = get_logging_context()
        logger.info("operation_completed", extra=context)
    """
    return {
        "request_id": get_request_id(),
        "user_id": get_user_id(),
        "org_id": get_org_id(),
    }


def log_with_context(
    logger: logging.Logger,
    level: int,
    message: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Log message with automatic request context injection.

    Convenience function that merges get_logging_context() with custom extra fields.

    Args:
        logger: Logger instance to use
        level: Logging level (logging.INFO, logging.WARNING, etc.)
        message: Log message
        extra: Additional fields to include in log entry

    Example:
        log_with_context(
            logger,
            logging.INFO,
            "organization_created",
            extra={"organization_id": str(org.id), "name": org.name}
        )
    """
    merged_extra = get_logging_context()
    if extra:
        merged_extra.update(extra)
    logger.log(level, message, extra=merged_extra)


class LoggingMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for request-scoped structured logging.

    This middleware:
    1. Extracts or generates request ID from X-Request-ID header
    2. Stores request ID in ContextVar for async-safe access
    3. Extracts user context from request.state (populated by AuthMiddleware)
    4. Stores user_id and org_id in ContextVars
    5. Logs request start and completion with timing

    The middleware must run BEFORE AuthMiddleware to initialize request context,
    but user context is populated AFTER authentication completes.

    Usage in main.py:
        from redact_api.core.logging import LoggingMiddleware
        app.add_middleware(LoggingMiddleware)  # Add before AuthMiddleware
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Process request and populate logging context.

        Args:
            request: FastAPI Request object
            call_next: Next middleware in chain

        Returns:
            Response from downstream middleware/endpoint
        """
        # Extract or generate request ID
        request_id = request.headers.get(settings.request_id_header, str(uuid.uuid4()))
        set_request_id(request_id)

        # Log request start (user context not yet available)
        if settings.include_request_context_in_logs:
            LOGGER.info(
                "request_started",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "client_host": request.client.host if request.client else None,
                },
            )

        # Process request (auth middleware will populate request.state.user)
        response = await call_next(request)

        # Extract user context after authentication (if available)
        user = getattr(request.state, "user", None)
        if user and settings.include_request_context_in_logs:
            user_id = str(user.id)
            org_id = str(user.organization_id) if user.organization_id else None
            set_user_context(user_id, org_id)

            # Log request completion with user context
            LOGGER.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "org_id": org_id,
                    "status_code": response.status_code,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
        elif settings.include_request_context_in_logs:
            # Log completion for unauthenticated requests
            LOGGER.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "method": request.method,
                    "path": request.url.path,
                },
            )

        # Add request ID to response headers for client correlation
        response.headers[settings.request_id_header] = request_id

        return response


def get_logger(name: str) -> logging.Logger:
    """Get logger instance with module name.

    This is a convenience function that wraps logging.getLogger().
    Use this consistently across the application for uniform logger naming.

    Args:
        name: Logger name (typically __name__ from calling module)

    Returns:
        Logger instance

    Example:
        logger = get_logger(__name__)
        logger.info("operation_started", extra=get_logging_context())
    """
    return logging.getLogger(name)
