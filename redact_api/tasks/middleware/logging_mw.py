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
    ``JobContextMiddleware`` (which runs after this one in the pipeline); this
    middleware records the lifecycle boundaries with the task id and name.
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
        ``task_exception`` line already covers the failure case (with a real traceback --
        see ``on_error``). Logging here too would double-log the same failure.
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
        """Log a task that raised, with its traceback.

        Why: TaskIQ's receiver invokes ``on_error`` after its own ``except`` block has
        already exited, so ``sys.exc_info()`` is empty here -- ``LOGGER.exception(...)``
        would log no traceback at all. Passing ``exception`` explicitly via ``exc_info``
        is what actually captures it.
        """
        LOGGER.error(
            "task_exception",
            exc_info=exception,
            extra={
                **get_logging_context(),
                "task_id": message.task_id,
                "task_name": message.task_name,
                "exception_type": type(exception).__name__,
            },
        )
