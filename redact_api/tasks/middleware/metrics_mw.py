"""Prometheus metrics middleware for task execution (redact-api#8).

Shape-copied from the worker template's ``metrics_mw``: increments the started counter
and in-progress gauge in ``pre_execute``, records duration + the completed counter in
``post_execute`` on success, and covers a raised task in ``on_error`` (decrement gauge,
increment failed, still record duration). There is no retried counter -- this pipeline has
no retry edge.

Why: TaskIQ's receiver calls BOTH ``on_error`` and ``post_execute`` when a task raises (this
is TaskIQ's own contract, not a bug here). ``on_error`` fully owns the failure path, so
``post_execute`` must skip all of its recording when ``result.is_err`` is true -- otherwise
every failure double-counts (gauge decremented twice, ``tasks_failed_total`` incremented
twice, duration observed twice).
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
        """Record success metrics (duration + completed counter).

        Skips all recording when ``result.is_err`` is true: ``on_error`` already fully
        owns the failure path (gauge decrement, ``tasks_failed_total``, duration), and
        TaskIQ's receiver calls both hooks on a raised task, so recording here too would
        double-count.
        """
        if result.is_err:
            return
        tasks_in_progress.labels(task_name=message.task_name).dec()
        self._observe_duration(message)
        tasks_completed_total.labels(environment=settings.environment, task_name=message.task_name).inc()

    async def on_error(
        self,
        message: TaskiqMessage,
        _result: TaskiqResult[Any],
        _exception: BaseException,
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
