"""Worker entrypoint for the redaction TaskIQ pipeline (redact-api#8).

Run with: ``taskiq worker redact_api.tasks.worker:broker``. Importing this module
registers the middleware pipeline and (via ``import redact_api.tasks``) every
``@broker.task``, so the worker process has the full task set on startup.
"""

from __future__ import annotations

import logging

import redact_api.tasks  # noqa: F401  # trigger @broker.task registration
from redact_api.core.config import settings
from redact_api.tasks.broker import broker
from redact_api.tasks.middleware import register_middleware

LOGGER = logging.getLogger(__name__)

register_middleware(broker)


@broker.on_event("startup")  # type: ignore[arg-type]
async def on_startup(state: object) -> None:
    """Validate configuration on worker startup and log readiness."""
    warnings = settings.validate_config()
    for warning in warnings:
        LOGGER.warning("config_warning", extra={"detail": warning})
    LOGGER.info("worker_started", extra={"app_name": settings.app_name, "environment": settings.environment})
