"""Logging middleware: log task lifecycle events with correlation context."""

from __future__ import annotations

import logging
from typing import Any

from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

from redact_api.core.logging import get_logging_context

LOGGER = logging.getLogger(__name__)


class LoggingMiddleware(TaskiqMiddleware):
    """Emit structured task_started / task_completed / task_error log lines.

    Correlation of a task's *own* log lines to its job id is handled by
    ``JobContextMiddleware`` (registered *outermost*, i.e. before this one in
    ``register_middleware``); this middleware records the lifecycle boundaries with the
    task id and name, and (via ``get_logging_context()``) also picks up ``job_id`` from
    that middleware's ContextVar. See ``redact_api/tasks/middleware/__init__.py`` for why
    the registration order matters.
    """

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Log task start."""
        LOGGER.info(
            "task_started",
            extra={**get_logging_context(), "task_id": message.task_id, "task_name": message.task_name},
        )
        return message

    async def post_execute(self, message: TaskiqMessage, result: TaskiqResult[Any]) -> None:
        """Log task completion.

        Skips logging when ``result.is_err`` is true: TaskIQ's receiver calls both
        ``on_error`` and ``post_execute`` when a task raises, and ``on_error``'s
        ``task_exception`` line already covers the failure case (digest-only -- see
        ``on_error``). Logging here too would double-log the same failure.
        """
        if result.is_err:
            return
        context = {**get_logging_context(), "task_id": message.task_id, "task_name": message.task_name}
        LOGGER.info("task_completed", extra=context)

    async def on_error(
        self,
        message: TaskiqMessage,
        _result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        """Log a task that raised, digest-only (no raw message/traceback).

        Why: this pipeline persists real detected PII (Span.text), and a task can fail
        with an exception whose message happens to echo detected content (e.g. a DB
        error echoing an offending column value). Passing ``exc_info=exception`` here
        would let the ECS formatter (``ecs_logging.StdlibFormatter``) serialize the raw
        exception message and full traceback into the log record -- the exact PII-leak-
        via-logs risk ``ingest_job.py``/``detect_job.py``/``apply_job.py`` already avoid
        by logging only ``exception_type`` instead of calling ``LOGGER.exception()``.
        Match that same digest-only pattern here.
        """
        LOGGER.error(
            "task_exception",
            extra={
                **get_logging_context(),
                "task_id": message.task_id,
                "task_name": message.task_name,
                "exception_type": type(exception).__name__,
            },
        )
