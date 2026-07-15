"""Unit tests for the TaskIQ middleware pipeline (redact-api#8).

Middleware are driven directly with hand-built ``TaskiqMessage``/``TaskiqResult`` objects,
mirroring the worker template's ``test_middleware`` shape.
"""

from __future__ import annotations

import logging
from collections.abc import Generator

import pytest
from prometheus_client import Histogram
from taskiq import TaskiqMessage, TaskiqResult

from redact_api.core.config import settings
from redact_api.core.logging import _job_id_var, get_job_id, get_logging_context
from redact_api.core.metrics import (
    task_duration_seconds,
    tasks_completed_total,
    tasks_failed_total,
    tasks_in_progress,
)
from redact_api.tasks.middleware.job_context import JobContextMiddleware
from redact_api.tasks.middleware.logging_mw import LoggingMiddleware
from redact_api.tasks.middleware.metrics_mw import MetricsMiddleware

_TASK_NAME = "redact_api.tasks.detect_job:detect_job"


@pytest.fixture(autouse=True)
def reset_job_context() -> Generator[None]:
    token = _job_id_var.set(None)
    yield
    _job_id_var.reset(token)


def _message(*, kwargs: dict[str, object] | None = None) -> TaskiqMessage:
    return TaskiqMessage(
        task_id="task-1",
        task_name=_TASK_NAME,
        labels={},
        labels_types=None,
        args=[],
        kwargs=kwargs or {},
    )


def _result(*, is_err: bool = False) -> TaskiqResult[None]:
    return TaskiqResult(is_err=is_err, return_value=None, execution_time=0.1, error=None)


class TestJobContextMiddleware:
    async def test_pre_execute_binds_job_id(self) -> None:
        middleware = JobContextMiddleware()
        await middleware.pre_execute(_message(kwargs={"job_id": "job-123"}))
        assert get_job_id() == "job-123"
        assert get_logging_context()["job_id"] == "job-123"

    async def test_pre_execute_without_job_id_leaves_context_unset(self) -> None:
        middleware = JobContextMiddleware()
        await middleware.pre_execute(_message(kwargs={}))
        assert get_job_id() is None

    async def test_post_execute_clears_job_id(self) -> None:
        middleware = JobContextMiddleware()
        await middleware.pre_execute(_message(kwargs={"job_id": "job-123"}))
        await middleware.post_execute(_message(kwargs={"job_id": "job-123"}), _result())
        assert get_job_id() is None

    async def test_on_error_clears_job_id(self) -> None:
        middleware = JobContextMiddleware()
        await middleware.pre_execute(_message(kwargs={"job_id": "job-123"}))
        await middleware.on_error(_message(kwargs={"job_id": "job-123"}), _result(is_err=True), ValueError("boom"))
        assert get_job_id() is None


class TestMetricsMiddleware:
    async def test_in_progress_gauge_incremented_then_decremented(self) -> None:
        middleware = MetricsMiddleware()
        gauge = tasks_in_progress.labels(task_name=_TASK_NAME)
        before = gauge._value.get()

        message = await middleware.pre_execute(_message())
        assert gauge._value.get() == before + 1

        await middleware.post_execute(message, _result())
        assert gauge._value.get() == before

    async def test_on_error_decrements_gauge(self) -> None:
        middleware = MetricsMiddleware()
        gauge = tasks_in_progress.labels(task_name=_TASK_NAME)
        before = gauge._value.get()

        message = await middleware.pre_execute(_message())
        await middleware.on_error(message, _result(is_err=True), RuntimeError("boom"))
        assert gauge._value.get() == before

    @staticmethod
    def _histogram_observation_count(histogram: Histogram) -> float:
        """Read a labeled histogram child's ``_count`` sample via the public ``collect()``.

        Histogram has no ``_count`` attribute directly (unlike Counter/Gauge's ``_value``)
        -- the total is only assembled at collection time from the per-bucket counters, so
        this goes through the public ``Collector`` API rather than a private attribute.
        """
        (metric,) = histogram.collect()
        (count_sample,) = (s for s in metric.samples if s.name.endswith("_count"))
        return count_sample.value

    async def test_failed_task_does_not_double_count(self) -> None:
        """Regression test: TaskIQ's receiver calls BOTH on_error and post_execute when a
        task raises (on_error from inside ``Receiver.run_task``, then post_execute on the
        same is_err=True result once run_task returns). Before the fix, post_execute
        unconditionally recorded failure metrics too, so a single failed task produced a
        net gauge change of -2 (should be -1, canceling the pre_execute +1) and incremented
        ``tasks_failed_total``/observed duration twice.
        """
        middleware = MetricsMiddleware()
        gauge = tasks_in_progress.labels(task_name=_TASK_NAME)
        failed_counter = tasks_failed_total.labels(environment=settings.environment, task_name=_TASK_NAME)
        completed_counter = tasks_completed_total.labels(environment=settings.environment, task_name=_TASK_NAME)
        duration_hist = task_duration_seconds.labels(task_name=_TASK_NAME)

        gauge_before = gauge._value.get()
        failed_before = failed_counter._value.get()
        completed_before = completed_counter._value.get()
        duration_count_before = self._histogram_observation_count(duration_hist)

        message = await middleware.pre_execute(_message())
        result = _result(is_err=True)
        exception = RuntimeError("boom")
        # Mirrors the real receiver's calling order: on_error fires inside run_task before
        # returning the is_err=True result; post_execute is then called on that same result.
        await middleware.on_error(message, result, exception)
        await middleware.post_execute(message, result)

        assert gauge._value.get() == gauge_before  # +1 (pre_execute), -1 (on_error), +0 (post_execute skipped)
        assert failed_counter._value.get() == failed_before + 1
        assert completed_counter._value.get() == completed_before
        assert self._histogram_observation_count(duration_hist) == duration_count_before + 1


class TestLoggingMiddleware:
    async def test_pre_execute_returns_message(self) -> None:
        middleware = LoggingMiddleware()
        message = _message(kwargs={"job_id": "job-1"})
        returned = await middleware.pre_execute(message)
        assert returned is message

    async def test_post_execute_handles_success_and_error(self) -> None:
        middleware = LoggingMiddleware()
        message = _message()
        # Neither branch should raise.
        await middleware.post_execute(message, _result())
        await middleware.post_execute(message, _result(is_err=True))

    async def test_failed_task_logs_traceback_exactly_once(self, caplog: pytest.LogCaptureFixture) -> None:
        """Regression test for two bugs:

        1. ``on_error`` used to call ``LOGGER.exception(...)``, which relies on
           ``sys.exc_info()`` -- but TaskIQ's receiver invokes ``on_error`` after its own
           ``except`` block has already exited, so no traceback was ever actually captured.
           Passing the exception explicitly via ``exc_info=exception`` fixes this.
        2. TaskIQ's receiver calls BOTH ``on_error`` and ``post_execute`` when a task raises,
           so the old ``post_execute`` (which logged ``task_error`` whenever
           ``result.is_err``) double-logged every failure alongside ``on_error``'s
           ``task_exception`` line.
        """
        middleware = LoggingMiddleware()
        message = _message()
        result = _result(is_err=True)
        exception = RuntimeError("boom")

        # Why: alembic/env.py calls logging.config.fileConfig(...) (default
        # disable_existing_loggers=True) once per test session, the first time the
        # session-scoped `engine` fixture runs migrations. That permanently sets
        # `.disabled = True` on every logger already created at that point -- including
        # this module's LOGGER, imported at collection time -- regardless of `caplog`'s
        # level handling. Reset it explicitly so this test is deterministic no matter
        # which other tests (and fixtures) ran first in the suite.
        logging.getLogger("redact_api.tasks.middleware.logging_mw").disabled = False

        with caplog.at_level(logging.INFO, logger="redact_api.tasks.middleware.logging_mw"):
            # Mirrors the real receiver's calling order: on_error fires inside run_task
            # before returning the is_err=True result; post_execute is then called on it.
            await middleware.on_error(message, result, exception)
            await middleware.post_execute(message, result)

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) == 1
        (record,) = error_records
        assert record.message == "task_exception"
        # A real traceback was captured (not an empty sys.exc_info()).
        assert record.exc_info is not None
        assert record.exc_info[1] is exception
        assert "task_error" not in [r.message for r in caplog.records]
