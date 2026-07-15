"""TaskIQ middleware registration for the redaction pipeline (redact-api#8).

Execution order: logging_mw -> job_context -> metrics_mw. Middleware runs
``pre_execute`` top-to-bottom and ``post_execute``/``on_error`` bottom-to-top. The
worker template's fourth ``state_tracking`` stage has no equivalent here -- redact-api
has no ``TaskExecution`` model (out of scope for this ticket).
"""

from __future__ import annotations

from taskiq import AsyncBroker

from redact_api.tasks.middleware.job_context import JobContextMiddleware
from redact_api.tasks.middleware.logging_mw import LoggingMiddleware
from redact_api.tasks.middleware.metrics_mw import MetricsMiddleware


def register_middleware(broker: AsyncBroker) -> None:
    """Register the middleware pipeline on ``broker`` in execution order."""
    broker.add_middlewares(
        LoggingMiddleware(),
        JobContextMiddleware(),
        MetricsMiddleware(),
    )
