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

from taskiq import AsyncBroker, InMemoryBroker

TASKIQ_ENV = os.environ.get("TASKIQ_ENV", "production")

# Dedicated queue for this service's ingest/detect/apply messages.
REDACT_API_QUEUE_NAME = "redact-api-tasks"

broker: AsyncBroker

if TASKIQ_ENV == "test":
    broker = InMemoryBroker()
else:
    from taskiq_aio_pika import AioPikaBroker
    from taskiq_aio_pika.queue import Queue, QueueType
    from taskiq_redis import RedisAsyncResultBackend

    from redact_api.core.config import settings

    broker = AioPikaBroker(
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
