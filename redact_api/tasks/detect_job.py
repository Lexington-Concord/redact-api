"""detect_job: run detection and advance INGESTED -> DETECTED -> IN_REVIEW (redact-api#8).

Loads the job (guard-first: a redelivered or already-advanced job no-op ACKs), re-derives
the page models from the original PDF (via ``extract_pages``), runs Tier-1 + Tier-2
detection and persists the candidate spans, then walks the job to its landed IN_REVIEW
state and logs that transition once. A detection error is unexpected: the job is moved to
FAILED, the terminal transition is logged, and the error re-raises as a task failure.
"""

from __future__ import annotations

import logging
from uuid import UUID

from redact_api.db import session as db_session
from redact_api.ingest.pdf import extract_pages
from redact_api.models.redaction_job import JobStatus
from redact_api.services.detection_service import run_detection
from redact_api.services.redaction_job_service import transition_job_status
from redact_api.storage import keys
from redact_api.tasks.broker import broker
from redact_api.tasks.support import build_storage_client, fail_job, load_job, log_job_terminal

LOGGER = logging.getLogger(__name__)


@broker.task
async def detect_job(job_id: str) -> None:
    """Detect PII for a job, persist spans, and advance it to IN_REVIEW."""
    async with db_session.async_session_maker() as session:
        job = await load_job(session, UUID(job_id))
        if job is None or job.status is not JobStatus.INGESTED:
            LOGGER.info("detect_job_skipped", extra={"job_id": job_id})
            return

        storage = build_storage_client()
        try:
            pdf_bytes = await storage.download_bytes(keys.original_pdf_key(job.document_id))
            pages = [extraction.page for extraction in extract_pages(pdf_bytes)]
            await run_detection(session, job.document_id, pages)
            await transition_job_status(session, job, JobStatus.DETECTED)
            # Why: land at IN_REVIEW and stop here -- apply_job is enqueued only by the
            # disposition-gated POST /jobs/{id}/apply endpoint, never automatically. A
            # human must review and disposition spans before the irreversible burn-in runs.
            await transition_job_status(session, job, JobStatus.IN_REVIEW)
            await session.commit()
        except Exception as exc:
            # Why: digest-only failure logging (no raw exception message/traceback) -- this
            # pipeline persists real detected PII (Span.text), and a future exception whose
            # message happens to echo detected content (e.g. a DB error echoing an offending
            # column value) must not leak raw PII into logs. Deliberately not
            # LOGGER.exception() -- that would attach the raw message/traceback via
            # exc_info=True, which is exactly what this must avoid.
            LOGGER.error(  # noqa: TRY400 - intentionally not .exception(): see comment above
                "detect_job_failed", extra={"job_id": job_id, "exception_type": type(exc).__name__}
            )
            await session.rollback()
            failed = await fail_job(UUID(job_id))
            if failed is not None:
                await log_job_terminal(failed, JobStatus.FAILED)
            raise

        await log_job_terminal(job, JobStatus.IN_REVIEW)
