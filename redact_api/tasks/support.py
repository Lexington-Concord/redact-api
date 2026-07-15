"""Shared helpers for the ingest/detect/apply tasks (redact-api#8).

Tasks run outside any HTTP request, so they build their own ``StorageClient`` from
settings and open their own sessions via ``db_session.async_session_maker`` (referenced
through the module so tests that repoint it to the worker DB are honored). ``fail_job``
and ``log_job_terminal`` centralize the FAILED-transition and terminal activity-logging
that every task shares.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from redact_api.core.activity_logging import log_activity
from redact_api.core.config import settings
from redact_api.db import session as db_session
from redact_api.models.activity_log import ActivityAction
from redact_api.models.redaction_job import JobStatus, RedactionJob
from redact_api.services.redaction_job_service import VALID_TRANSITIONS, transition_job_status
from redact_api.storage.client import StorageClient


def build_storage_client() -> StorageClient:
    """Construct a MinIO ``StorageClient`` from settings (tasks have no ``app.state``)."""
    return StorageClient(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
    )


async def load_job(session: AsyncSession, job_id: UUID) -> RedactionJob | None:
    """Load a job by id, or ``None`` if it no longer exists."""
    result = await session.execute(select(RedactionJob).where(col(RedactionJob.id) == job_id))
    return result.scalar_one_or_none()


async def fail_job(job_id: UUID) -> RedactionJob | None:
    """Move a job to FAILED in a fresh session (best-effort).

    Opens its own session so it is safe to call after the task's working session has been
    rolled back. Only transitions if the job's current state permits a move to FAILED;
    returns the (reloaded) job so the caller can log its terminal transition, or ``None``
    if the job no longer exists.
    """
    async with db_session.async_session_maker() as session:
        job = await load_job(session, job_id)
        if job is None:
            return None
        if JobStatus.FAILED in VALID_TRANSITIONS[job.status]:
            await transition_job_status(session, job, JobStatus.FAILED)
            await session.commit()
        return job


async def log_job_terminal(job: RedactionJob, status: JobStatus) -> None:
    """Fire-and-forget activity log of a task's terminal job-status transition (Section 5).

    Uses the session-less (fire-and-forget) ``log_activity`` branch, so a logging failure
    can never roll back or block the task's already-committed work.
    """
    await log_activity(
        action=ActivityAction.UPDATE,
        resource_type="redaction_job",
        resource_id=job.id,
        details={"status": status.value, "document_id": str(job.document_id)},
    )
