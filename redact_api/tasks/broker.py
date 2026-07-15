"""TaskIQ broker singleton for the redaction async pipeline (redact-api#8).

Uses an ``InMemoryBroker`` under ``TASKIQ_ENV=test`` (so the suite drives ingest/detect/
apply in-process, with no RabbitMQ/Redis), and an ``AioPikaBroker`` + Redis result
backend in production. The broker type is decided at import time from ``TASKIQ_ENV`` and
cannot be changed later, so tests must set that env var before importing this module.

Deviation from the worker template's ``broker.py``: that template sets ``declare=False``
because a separate API process declares the queue first. redact-api owns its queue end
to end -- the same FastAPI app both publishes tasks and (via its worker process) consumes
them, with no upstream declarer -- so it declares the queue itself (``declare=True``).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from taskiq import AsyncBroker, InMemoryBroker

if TYPE_CHECKING:
    from taskiq_aio_pika import AioPikaBroker

TASKIQ_ENV = os.environ.get("TASKIQ_ENV", "production")

# Dedicated queue for this service's ingest/detect/apply messages.
REDACT_API_QUEUE_NAME = "redact-api-tasks"


def build_production_broker() -> AioPikaBroker:
    """Construct the RabbitMQ + Redis broker for non-test environments.

    ``declare=True`` because redact-api owns its queue end to end (no separate API process
    declares it first, unlike the worker template's ``declare=False``). Constructing the
    broker opens no connection, so this is safe to call in a unit test.
    """
    from taskiq_aio_pika import AioPikaBroker
    from taskiq_aio_pika.queue import Queue, QueueType
    from taskiq_redis import RedisAsyncResultBackend

    from redact_api.core.config import settings

    return AioPikaBroker(
        url=settings.rabbitmq_url,
        dead_letter_queue=None,
        task_queues=[
            Queue(
                name=REDACT_API_QUEUE_NAME,
                type=QueueType.CLASSIC,
                durable=True,
                declare=True,
            ),
        ],
    ).with_result_backend(RedisAsyncResultBackend(redis_url=settings.redis_url))


broker: AsyncBroker = InMemoryBroker() if TASKIQ_ENV == "test" else build_production_broker()
