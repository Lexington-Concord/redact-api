"""Async ingest/detect/apply task package for the redaction pipeline (redact-api#8).

Importing this package registers every ``@broker.task`` with the broker singleton, so
the worker entrypoint (``redact_api.tasks.worker``) and the API seam both trigger
registration simply by importing it.
"""

from __future__ import annotations

from redact_api.tasks.apply_job import apply_job
from redact_api.tasks.detect_job import detect_job
from redact_api.tasks.ingest_job import ingest_job

__all__ = ["apply_job", "detect_job", "ingest_job"]
