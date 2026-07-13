"""FastAPI application entrypoint and middleware configuration.

Middleware Execution Order
--------------------------
FastAPI middleware executes in REVERSE order of addition:
- Last added middleware = FIRST to process requests
- First added middleware = LAST to process requests

Current middleware stack (request flow):
1. SlowAPIMiddleware (rate limiting) - added last, executes first
2. LoggingMiddleware - added second-to-last
3. TenantIsolationMiddleware - added third
4. AuthMiddleware - added fourth
5. CORSMiddleware - added first, executes last before endpoint

Response flow is the reverse (CORS first, SlowAPI last).

Performance Implications
------------------------
- CORS: Minimal overhead, only affects preflight requests
- Rate Limiting: Redis lookup per request (~1-2ms)
- Structured Logging: ContextVar operations, negligible overhead (<0.1ms)
- Authentication: JWT validation (~5-10ms for RS256)
- Tenant Isolation: Database lookup if not cached (~5-20ms)

Each middleware below is commented with configuration requirements.
Uncomment sections as needed for your deployment.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi_pagination import add_pagination
from pydantic import ValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import text

from redact_api.api.admin import router as admin_internal_router
from redact_api.api.admin import webhooks_router as admin_webhooks_router
from redact_api.api.routes import router as api_router
from redact_api.core.config import ConfigurationError, settings
from redact_api.core.logging import LoggingMiddleware
from redact_api.core.metrics import metrics_app
from redact_api.core.pagination import configure_pagination
from redact_api.db.session import PoolConfig, create_db_engine, create_session_maker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan - initialize and cleanup resources.

    Replaces deprecated @app.on_event("startup") and @app.on_event("shutdown").
    Initializes database engine and session maker, validates connectivity,
    and ensures proper cleanup on shutdown.

    This pattern is pytest-xdist compatible because each test worker can
    inject its own engine/session_maker into app.state via fixtures,
    rather than relying on module-level globals.

    Yields:
        None after startup completes, resumes for shutdown on context exit.
    """
    # Startup: Validate configuration first (fail fast on misconfiguration)
    try:
        config_warnings = settings.validate_config()
        for warning in config_warnings:
            logger.warning("Configuration warning: %s", warning)
    except ConfigurationError:
        logger.exception("Configuration validation failed")
        raise

    # Startup: Initialize database engine and session maker
    pool_config = PoolConfig(
        size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        timeout=settings.db_pool_timeout,
        recycle=settings.db_pool_recycle,
        pre_ping=settings.db_pool_pre_ping,
    )
    app.state.engine = create_db_engine(
        settings.database_url,
        echo=settings.sqlalchemy_echo,
        pool=pool_config,
    )
    app.state.async_session_maker = create_session_maker(app.state.engine)

    # Validate database connectivity (fail fast)
    try:
        async with app.state.engine.begin() as connection:
            await connection.execute(text("SELECT 1"))

        # Sanitize URL before logging (remove credentials)
        safe_url = str(settings.database_url).split("@")[-1]
        logger.info("Database connection successful: %s", safe_url)
    except Exception as exc:
        db_url = settings.database_url
        error_msg = f"Failed to connect to database on startup: {exc}. Check DATABASE_URL={db_url}"
        raise RuntimeError(error_msg) from exc

    yield

    # Shutdown: Clean up resources
    logger.info("Shutting down: draining database connection pool")
    await app.state.engine.dispose()
    logger.info("Shutdown complete: all database connections closed")


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(api_router)
# Internal/admin endpoints (/_admin namespace)
# SECURITY: Must be blocked from external access via Traefik
app.include_router(admin_internal_router)
app.include_router(admin_webhooks_router)
configure_pagination()
add_pagination(app)

if settings.enable_metrics:
    app.mount("/metrics", metrics_app)

# ============================================================================
# Middleware Configuration
# ============================================================================
# Middleware is processed in REVERSE order (last added = first executed)
# Order them carefully to ensure correct request processing flow

# CORS Middleware
# Cross-Origin Resource Sharing for frontend applications.
# CRITICAL: In production, restrict origins to your actual frontend domains.
# Never use allow_origins=["*"] in production (security risk).
#
# Configuration in .env:
#   CORS_ALLOWED_ORIGINS=http://localhost:3000
#
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,  # ['http://localhost:3000']
    allow_credentials=True,  # Allow cookies/auth headers
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],  # Explicit list
    allow_headers=["Authorization", "Content-Type"],  # Explicit list
)

# Rate Limiting Middleware
# Protects against brute force attacks and DoS by limiting requests per IP.
# Default limits: 100 requests/minute, 2000 requests/hour
#
# Requires: pip install slowapi
#
# Configuration in .env:
#   RATE_LIMIT_ENABLED=true (default)
#   RATE_LIMIT_PER_MINUTE=100 (default)
#   RATE_LIMIT_PER_HOUR=2000 (default)
#
# Per-endpoint limits can override defaults:
#   @router.get("/sensitive-endpoint")
#   @limiter.limit("10/minute")
#   async def sensitive_operation(request: Request):
#       ...
#
# Documentation: https://slowapi.readthedocs.io/
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute", "2000/hour"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)

# Structured Logging Middleware
# Automatically adds request_id, user_id, org_id to all logs
# Configuration in .env:
#   REQUEST_ID_HEADER=x-request-id (default)
#   INCLUDE_REQUEST_CONTEXT_IN_LOGS=true (default)
#
# IMPORTANT: Add BEFORE AuthMiddleware to initialize request context early.
# The middleware will:
# 1. Extract or generate request ID from X-Request-ID header
# 2. Store request_id in ContextVar (available throughout request lifecycle)
# 3. After auth completes, extract user_id and org_id from request.state.user
# 4. Make all context available to services via get_logging_context()
#
# Example usage in services:
#   from redact_api.core.logging import get_logging_context
#   logger.info("operation", extra=get_logging_context())
#
app.add_middleware(LoggingMiddleware)

# Authentication Middleware (DISABLED)
# To enable authentication:
#   1. Regenerate project with copier and set auth_enabled=true
#   2. Or manually uncomment the following and configure .env:
#
# from redact_api.core.auth import AuthMiddleware
# app.add_middleware(AuthMiddleware)
#
# Configuration required in .env:
#   AUTH_PROVIDER_TYPE=ory|auth0|keycloak|cognito
#   AUTH_PROVIDER_URL=https://your-auth-provider.com
#   AUTH_PROVIDER_ISSUER=https://your-auth-provider.com/
#   JWT_ALGORITHM=RS256
#   JWT_PUBLIC_KEY=<your-public-key-pem>
# Tenant Isolation Middleware (DISABLED - Authentication Required)
# Multi-tenant isolation requires authentication to be enabled first.
# To enable:
#   1. Regenerate project with copier and set auth_enabled=true
#   2. Or manually enable AuthMiddleware above, then uncomment:
#
# from redact_api.core.tenants import TenantIsolationMiddleware
# app.add_middleware(TenantIsolationMiddleware)

# Global Exception Handlers
# These provide consistent error responses across the entire API


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,  # noqa: ARG001 - Required by FastAPI signature
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle Pydantic validation errors from request payloads.

    Returns structured 422 response with detailed validation error information.
    FastAPI uses RequestValidationError for request body validation failures.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "error_code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": exc.errors(),
        },
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(
    request: Request,  # noqa: ARG001 - Required by FastAPI signature
    exc: ValidationError,
) -> JSONResponse:
    """Handle Pydantic validation errors from internal model validation.

    Returns structured 422 response with detailed validation error information.
    This catches ValidationError raised in service layer or business logic.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "error_code": "VALIDATION_ERROR",
            "message": "Data validation failed",
            "details": exc.errors(),
        },
    )


@app.exception_handler(ValueError)
async def value_error_exception_handler(
    request: Request,  # noqa: ARG001 - Required by FastAPI signature
    exc: ValueError,
) -> JSONResponse:
    """Handle ValueError as 400 Bad Request.

    ValueError typically indicates invalid input data that passed initial
    validation but failed business logic validation (e.g., invalid UUID format,
    out-of-range values).
    """
    error_message = str(exc) if str(exc) else "Invalid value provided"
    logger.warning("ValueError in request: %s", error_message, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "status_code": status.HTTP_400_BAD_REQUEST,
            "error_code": "INVALID_VALUE",
            "message": error_message,
        },
    )


@app.exception_handler(TypeError)
async def type_error_exception_handler(
    request: Request,  # noqa: ARG001 - Required by FastAPI signature
    exc: TypeError,
) -> JSONResponse:
    """Handle TypeError as 400 Bad Request.

    TypeError typically indicates incorrect data types in the request,
    which suggests a client error in how the API is being called.
    """
    error_message = str(exc) if str(exc) else "Invalid type provided"
    logger.warning("TypeError in request: %s", error_message, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "status_code": status.HTTP_400_BAD_REQUEST,
            "error_code": "INVALID_TYPE",
            "message": error_message,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(
    request: Request,  # noqa: ARG001 - Required by FastAPI signature
    exc: Exception,
) -> JSONResponse:
    """Handle unexpected exceptions as 500 Internal Server Error.

    Logs full exception details for debugging but returns sanitized message
    to clients to avoid leaking internal implementation details.
    This is a catch-all handler for any unhandled exceptions.
    """
    # Log full exception details for debugging
    logger.exception("Unhandled exception in request", exc_info=exc)

    # Return sanitized error to client (no internal details)
    sanitized_message = "An internal server error occurred"
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error_code": "INTERNAL_ERROR",
            "message": sanitized_message,
        },
    )
