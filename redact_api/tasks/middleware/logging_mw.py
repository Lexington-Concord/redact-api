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
        """Log task completion or a returned-error result."""
        context = {**get_logging_context(), "task_id": message.task_id, "task_name": message.task_name}
        if result.is_err:
            LOGGER.error("task_error", extra={**context, "error": str(result.error)})
        else:
            LOGGER.info("task_completed", extra=context)

    async def on_error(
        self,
        message: TaskiqMessage,
        _result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        """Log a task that raised."""
        LOGGER.exception(
            "task_exception",
            extra={
                **get_logging_context(),
                "task_id": message.task_id,
                "task_name": message.task_name,
                "exception_type": type(exception).__name__,
            },
        )
