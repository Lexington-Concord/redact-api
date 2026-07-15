"""Prometheus metrics middleware for task execution (redact-api#8).

Shape-copied from the worker template's ``metrics_mw``: increments the started counter
and in-progress gauge in ``pre_execute``, records duration + the completed/failed counter
in ``post_execute``, and covers a raised task in ``on_error`` (decrement gauge, increment
failed, still record duration). There is no retried counter -- this pipeline has no retry
edge.
"""

from __future__ import annotations

import time
from typing import Any

from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

from redact_api.core.config import settings
from redact_api.core.metrics import (
    task_duration_seconds,
    tasks_completed_total,
    tasks_failed_total,
    tasks_in_progress,
    tasks_started_total,
)

_TASK_START_TIME_KEY = "_metrics_start_time"


class MetricsMiddleware(TaskiqMiddleware):
    """Record Prometheus metrics across a task's execution."""

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Record task start and increment the in-progress gauge."""
        tasks_started_total.labels(environment=settings.environment, task_name=message.task_name).inc()
        tasks_in_progress.labels(task_name=message.task_name).inc()
        message.labels[_TASK_START_TIME_KEY] = str(time.monotonic())
        return message

    async def post_execute(self, message: TaskiqMessage, result: TaskiqResult[Any]) -> None:
        """Record completion metrics (duration + completed/failed counter)."""
        tasks_in_progress.labels(task_name=message.task_name).dec()
        self._observe_duration(message)
        if result.is_err:
            tasks_failed_total.labels(environment=settings.environment, task_name=message.task_name).inc()
        else:
            tasks_completed_total.labels(environment=settings.environment, task_name=message.task_name).inc()

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        """Record failure metrics when a task raises."""
        tasks_in_progress.labels(task_name=message.task_name).dec()
        tasks_failed_total.labels(environment=settings.environment, task_name=message.task_name).inc()
        self._observe_duration(message)

    @staticmethod
    def _observe_duration(message: TaskiqMessage) -> None:
        """Observe elapsed wall time since ``pre_execute`` stamped the start."""
        start_time_str = message.labels.get(_TASK_START_TIME_KEY)
        if start_time_str is not None:
            duration = time.monotonic() - float(start_time_str)
            task_duration_seconds.labels(task_name=message.task_name).observe(duration)
