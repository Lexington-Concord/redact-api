"""Job-context middleware: bind the processing job id into the logging context.

Fills the pipeline position the worker template gives to tenant extraction, but this
service's tasks carry no tenant id -- they are single-tenant and ``job_id``-only. Copying
the template's ``TenantMiddleware`` verbatim would be dead code (it looks only for a
``tenant_id`` kwarg that never exists here), so this middleware extracts the ``job_id``
kwarg every task does carry and binds it, so every log line the task emits during
execution is correlatable to the job it is processing.
"""

from __future__ import annotations

import logging
from typing import Any

from taskiq import TaskiqMessage, TaskiqMiddleware, TaskiqResult

from redact_api.core.logging import clear_job_context, set_job_context

LOGGER = logging.getLogger(__name__)

JOB_ID_KEY = "job_id"


class JobContextMiddleware(TaskiqMiddleware):
    """Set the job-id logging ContextVar for the duration of a task's execution."""

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Bind the task's job_id kwarg into the logging context."""
        job_id = message.kwargs.get(JOB_ID_KEY)
        if job_id is not None:
            set_job_context(str(job_id))
            LOGGER.debug("job_context_set", extra={"job_id": str(job_id), "task_id": message.task_id})
        return message

    async def post_execute(self, message: TaskiqMessage, result: TaskiqResult[Any]) -> None:
        """Clear the job-id context after the task completes."""
        clear_job_context()

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        """Clear the job-id context after the task raises."""
        clear_job_context()
