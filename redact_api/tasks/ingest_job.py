"""ingest_job: stage a job's PDF artifacts and advance UPLOADED -> INGESTED (redact-api#8).

Loads the job (guard-first: a redelivered or already-advanced job no-op ACKs), downloads
the original PDF, runs the full ``ingest_pdf`` (which uploads per-page raster + text-layer
artifacts), moves the job to INGESTED, then chains ``detect_job``. An ingest rejection
(oversized / encrypted / malformed / unsupported page) is an expected outcome: the job is
moved to FAILED and the task completes normally. Any other error propagates as a task
failure after the job is marked FAILED.
"""

from __future__ import annotations

import logging
from uuid import UUID

from redact_api.db import session as db_session
from redact_api.ingest.exceptions import (
    DocumentTooLargeError,
    EncryptedPdfError,
    MalformedPdfError,
    UnsupportedPageError,
)
from redact_api.ingest.service import ingest_pdf
from redact_api.models.redaction_job import JobStatus
from redact_api.services.redaction_job_service import transition_job_status
from redact_api.storage import keys
from redact_api.tasks.broker import broker
from redact_api.tasks.detect_job import detect_job
from redact_api.tasks.support import build_storage_client, fail_job, load_job, log_job_terminal

LOGGER = logging.getLogger(__name__)


@broker.task
async def ingest_job(job_id: str) -> None:
    """Ingest a job's PDF, advance it to INGESTED, and enqueue detection."""
    async with db_session.async_session_maker() as session:
        job = await load_job(session, UUID(job_id))
        if job is None or job.status is not JobStatus.UPLOADED:
            LOGGER.info("ingest_job_skipped", extra={"job_id": job_id})
            return

        storage = build_storage_client()
        try:
            pdf_bytes = await storage.download_bytes(keys.original_pdf_key(job.document_id))
            await ingest_pdf(job.document_id, pdf_bytes, storage)
            await transition_job_status(session, job, JobStatus.INGESTED)
            await session.commit()
        except (DocumentTooLargeError, EncryptedPdfError, MalformedPdfError, UnsupportedPageError):
            LOGGER.warning("ingest_job_rejected", extra={"job_id": job_id})
            await session.rollback()
            failed = await fail_job(UUID(job_id))
            if failed is not None:
                await log_job_terminal(failed, JobStatus.FAILED)
            return
        except Exception as exc:
            # Why: digest-only failure logging (no raw exception message/traceback) -- this
            # pipeline persists real detected PII (Span.text), and a future exception whose
            # message happens to echo detected content (e.g. a DB error echoing an offending
            # column value) must not leak raw PII into logs. Deliberately not
            # LOGGER.exception() -- that would attach the raw message/traceback via
            # exc_info=True, which is exactly what this must avoid.
            LOGGER.error(  # noqa: TRY400 - intentionally not .exception(): see comment above
                "ingest_job_failed", extra={"job_id": job_id, "exception_type": type(exc).__name__}
            )
            await session.rollback()
            failed = await fail_job(UUID(job_id))
            if failed is not None:
                await log_job_terminal(failed, JobStatus.FAILED)
            raise

        await log_job_terminal(job, JobStatus.INGESTED)

    await detect_job.kiq(job_id=job_id)
