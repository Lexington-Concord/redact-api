"""Unit tests for the TaskIQ middleware pipeline (redact-api#8).

Middleware are driven directly with hand-built ``TaskiqMessage``/``TaskiqResult`` objects,
mirroring the worker template's ``test_middleware`` shape.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from taskiq import TaskiqMessage, TaskiqResult

from redact_api.core.logging import _job_id_var, get_job_id, get_logging_context
from redact_api.core.metrics import tasks_in_progress
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
