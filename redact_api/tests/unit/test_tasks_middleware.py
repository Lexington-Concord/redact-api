"""Unit tests for the TaskIQ middleware pipeline (redact-api#8).

Middleware are driven directly with hand-built ``TaskiqMessage``/``TaskiqResult`` objects,
mirroring the worker template's ``test_middleware`` shape.
"""

from __future__ import annotations

import logging
from collections.abc import Generator

import pytest
from prometheus_client import Histogram
from taskiq import InMemoryBroker, TaskiqMessage, TaskiqResult

from redact_api.core.config import settings
from redact_api.core.logging import _job_id_var, get_job_id, get_logging_context
from redact_api.core.metrics import (
    task_duration_seconds,
    tasks_completed_total,
    tasks_failed_total,
    tasks_in_progress,
)
from redact_api.tasks.middleware import register_middleware
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


def _extra(record: logging.LogRecord, field: str) -> object:
    """Read a field from a LogRecord's ``extra={...}`` dict.

    ``extra`` fields land as plain attributes on the record at emit time, but they are
    not part of ``logging.LogRecord``'s type stub -- ``getattr`` (rather than direct
    attribute access) avoids a mypy ``attr-defined`` error on every custom field this
    test suite asserts on.
    """
    return getattr(record, field)


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

    async def test_failed_task_logs_exception_digest_exactly_once(self, caplog: pytest.LogCaptureFixture) -> None:
        """Regression test for two bugs:

        1. ``on_error`` used to pass ``exc_info=exception`` to ``LOGGER.error(...)``. The
           ECS formatter (``ecs_logging.StdlibFormatter``) serializes ``exc_info`` into the
           raw exception message + full traceback -- a PII leak, since this pipeline
           persists real detected PII (Span.text) and a DB error could echo it. The fix
           logs only ``exception_type`` (digest-only), matching ``ingest_job.py`` /
           ``detect_job.py`` / ``apply_job.py``'s pattern -- no ``exc_info`` at all.
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
        # Digest-only: no exc_info/traceback attached, but exception_type is present.
        assert not record.exc_info
        assert _extra(record, "exception_type") == type(exception).__name__
        assert "task_error" not in [r.message for r in caplog.records]


class TestComposedMiddlewarePipeline:
    """Drives a real ``InMemoryBroker`` with all three middleware attached via
    ``register_middleware()`` -- the actual production composition -- rather than each
    middleware in isolation.

    Regression coverage for findings 1 and 3 (round 2): finding 3's registration-order bug
    only manifests when the middleware run together (``JobContextMiddleware`` must be
    outermost so ``LoggingMiddleware`` can still read ``job_id`` on the way out), and
    finding 1's PII leak is only meaningfully caught end to end, through the same log
    record shape the worker process actually emits.
    """

    @staticmethod
    def _reset_logging_mw_logger() -> None:
        # Why: see test_failed_task_logs_exception_digest_exactly_once -- Alembic's
        # fileConfig(disable_existing_loggers=True) can disable this module logger once
        # per test session; reset it so this test is deterministic regardless of suite
        # ordering.
        logging.getLogger("redact_api.tasks.middleware.logging_mw").disabled = False

    async def test_via_broker_success_logs_job_id_on_started_and_completed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._reset_logging_mw_logger()
        broker = InMemoryBroker()
        register_middleware(broker)

        @broker.task
        async def _ok_task(job_id: str) -> None:
            # job_id must be a real parameter (not just `**kwargs`) so `.kiq(job_id=...)`
            # binds correctly; the middleware pipeline is what this test exercises, not
            # the task body itself.
            _ = job_id

        job_id = "job-composed-success"
        with caplog.at_level(logging.INFO, logger="redact_api.tasks.middleware.logging_mw"):
            task = await _ok_task.kiq(job_id=job_id)
            result = await task.wait_result(check_interval=0.01)

        assert not result.is_err
        started = next(r for r in caplog.records if r.message == "task_started")
        completed = next(r for r in caplog.records if r.message == "task_completed")
        assert _extra(started, "job_id") == job_id
        assert _extra(completed, "job_id") == job_id

    async def test_via_broker_failure_logs_job_id_with_no_raw_exception_content(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._reset_logging_mw_logger()
        broker = InMemoryBroker()
        register_middleware(broker)

        secret_message = "raw pii span text that must never reach the log record"

        @broker.task
        async def _failing_task(job_id: str) -> None:
            _ = job_id  # see _ok_task above -- must be a real bindable parameter
            raise RuntimeError(secret_message)

        job_id = "job-composed-failure"
        with caplog.at_level(logging.INFO, logger="redact_api.tasks.middleware.logging_mw"):
            task = await _failing_task.kiq(job_id=job_id)
            result = await task.wait_result(check_interval=0.01)

        assert result.is_err
        started = next(r for r in caplog.records if r.message == "task_started")
        exc_record = next(r for r in caplog.records if r.message == "task_exception")
        assert _extra(started, "job_id") == job_id
        # job_id must still be bound when LoggingMiddleware's on_error runs -- this is
        # only true because JobContextMiddleware is registered outermost (finding 3).
        assert _extra(exc_record, "job_id") == job_id
        assert _extra(exc_record, "exception_type") == "RuntimeError"
        # Digest-only (finding 1): no exc_info/traceback, and the raw exception message
        # never appears in our own log record. (TaskIQ's own internal receiver logger
        # separately logs the raw exception with a full traceback via its own
        # `logger.error(..., exc_info=True)` call -- that's library-internal behavior
        # outside this codebase's control and outside this fix's scope; the assertion
        # here is scoped to the record our LoggingMiddleware itself produced.)
        assert not exc_record.exc_info
        assert secret_message not in exc_record.getMessage()
        assert "task_completed" not in [r.message for r in caplog.records]
