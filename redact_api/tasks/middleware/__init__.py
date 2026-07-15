"""TaskIQ middleware registration for the redaction pipeline (redact-api#8).

Execution order: job_context -> logging_mw -> metrics_mw. Middleware runs
``pre_execute`` top-to-bottom and ``post_execute``/``on_error`` bottom-to-top (TaskIQ's
``Receiver`` iterates ``reversed(broker.middlewares)`` for both -- confirmed against the
installed ``taskiq`` package), so ``JobContextMiddleware`` is registered *outermost*
(first) deliberately:

- On entry (``pre_execute``, top-to-bottom): ``JobContextMiddleware`` sets the ``job_id``
  ContextVar *before* ``LoggingMiddleware`` runs, so even the ``task_started`` log line
  carries ``job_id``.
- On exit (``post_execute``/``on_error``, bottom-to-top): ``JobContextMiddleware``
  unconditionally clears that ContextVar *last*, i.e. after ``LoggingMiddleware`` has
  already read it for the ``task_completed``/``task_exception`` line.

Registering ``LoggingMiddleware`` first (the original order) would have
``JobContextMiddleware.post_execute``/``on_error`` clear ``job_id`` *before*
``LoggingMiddleware`` reads it on the way out, so none of the completion/failure log
lines would ever carry ``job_id`` -- directly defeating ``JobContextMiddleware``'s
purpose. The worker template's fourth ``state_tracking`` stage has no equivalent here --
redact-api has no ``TaskExecution`` model (out of scope for this ticket).
"""

from __future__ import annotations

from taskiq import AsyncBroker

from redact_api.tasks.middleware.job_context import JobContextMiddleware
from redact_api.tasks.middleware.logging_mw import LoggingMiddleware
from redact_api.tasks.middleware.metrics_mw import MetricsMiddleware


def register_middleware(broker: AsyncBroker) -> None:
    """Register the middleware pipeline on ``broker`` in execution order."""
    broker.add_middlewares(
        JobContextMiddleware(),
        LoggingMiddleware(),
        MetricsMiddleware(),
    )
