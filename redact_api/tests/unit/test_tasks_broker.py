"""Unit tests for the TaskIQ broker singleton, queue config, and worker entrypoint (redact-api#8)."""

from __future__ import annotations

from taskiq import AsyncBroker, InMemoryBroker
from taskiq_aio_pika import AioPikaBroker

import redact_api.tasks.worker  # noqa: F401  # side effect: registers tasks + middleware on the broker
from redact_api.tasks.broker import REDACT_API_QUEUE_NAME, broker, build_production_broker
from redact_api.tasks.middleware import register_middleware
from redact_api.tasks.middleware.job_context import JobContextMiddleware
from redact_api.tasks.middleware.logging_mw import LoggingMiddleware
from redact_api.tasks.middleware.metrics_mw import MetricsMiddleware


class TestBrokerSingleton:
    def test_test_env_uses_in_memory_broker(self) -> None:
        # The suite runs with TASKIQ_ENV=test (conftest), so the singleton is in-memory.
        assert isinstance(broker, InMemoryBroker)

    def test_queue_name_is_dedicated(self) -> None:
        assert REDACT_API_QUEUE_NAME == "redact-api-tasks"


class TestProductionBroker:
    def test_builds_aio_pika_broker(self) -> None:
        production = build_production_broker()
        assert isinstance(production, AioPikaBroker)

    def test_declares_its_own_durable_classic_queue(self) -> None:
        # redact-api owns its queue end to end -> declare=True (deviates from worker template).
        production = build_production_broker()
        queue = production._task_queues[0]
        assert queue.name == REDACT_API_QUEUE_NAME
        assert queue.declare is True
        assert queue.durable is True


class TestMiddlewarePipeline:
    def test_register_middleware_order(self) -> None:
        fresh: AsyncBroker = InMemoryBroker()
        register_middleware(fresh)
        assert [type(m).__name__ for m in fresh.middlewares] == [
            LoggingMiddleware.__name__,
            JobContextMiddleware.__name__,
            MetricsMiddleware.__name__,
        ]


class TestWorkerEntrypoint:
    def test_worker_import_registers_tasks_and_middleware(self) -> None:
        # Importing the worker (module top) triggered @broker.task registration + middleware wiring.
        registered = broker.get_all_tasks()
        task_names = {task.task_name for task in registered.values()}
        assert any(name.endswith("ingest_job") for name in task_names)
        assert any(name.endswith("detect_job") for name in task_names)
        assert any(name.endswith("apply_job") for name in task_names)
        assert [type(m).__name__ for m in broker.middlewares] == [
            LoggingMiddleware.__name__,
            JobContextMiddleware.__name__,
            MetricsMiddleware.__name__,
        ]
