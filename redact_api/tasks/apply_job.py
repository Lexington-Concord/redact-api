"""apply_job: burn approved spans and advance APPLYING -> VERIFIED / FAILED (redact-api#8).

The endpoint validates the IN_REVIEW -> APPLYING edge synchronously; this task picks the
job up at APPLYING (guard-first: any other state no-op ACKs), downloads the original,
projects the approved spans, and runs the irreversible ``apply`` burn-in. A verify-gate
FAIL is an expected outcome -- the job moves to FAILED and the task completes normally. A
malformed-bbox projection error or any other unexpected error moves the job to FAILED and
re-raises as a task failure.
"""

from __future__ import annotations

import logging
from uuid import UUID

from redact_api.db import session as db_session
from redact_api.models.redaction_job import JobStatus
from redact_api.redaction.apply import apply
from redact_api.services.jobs_service import project_approved_spans
from redact_api.services.redaction_job_service import transition_job_status
from redact_api.storage import keys
from redact_api.tasks.broker import broker
from redact_api.tasks.support import build_storage_client, fail_job, load_job, log_job_terminal

LOGGER = logging.getLogger(__name__)

_PDF_CONTENT_TYPE = "application/pdf"


@broker.task
async def apply_job(job_id: str) -> None:
    """Burn approved spans into a job's PDF, gate through verify, and land VERIFIED/FAILED."""
    async with db_session.async_session_maker() as session:
        job = await load_job(session, UUID(job_id))
        if job is None or job.status is not JobStatus.APPLYING:
            LOGGER.info("apply_job_skipped", extra={"job_id": job_id})
            return

        storage = build_storage_client()
        try:
            original_bytes = await storage.download_bytes(keys.original_pdf_key(job.document_id))
            approved_spans = await project_approved_spans(session, job)
            result = apply(original_bytes, approved_spans)

            if not result.passed:
                # Digest-only diagnostics (verdict + finding count) -- never the raw
                # redacted text. See VerifyFinding.redacted_string_digest (R4): findings
                # never carry the recoverable string itself, only a digest.
                LOGGER.warning(
                    "apply_job_verify_failed",
                    extra={
                        "job_id": job_id,
                        "verdict": result.verify_result.verdict.value,
                        "finding_count": len(result.verify_result.findings),
                    },
                )
                await transition_job_status(session, job, JobStatus.FAILED)
                await session.commit()
                await log_job_terminal(job, JobStatus.FAILED)
                return

            redacted_key = keys.redacted_pdf_key(job.id)
            await storage.upload_bytes(redacted_key, result.pdf_bytes, content_type=_PDF_CONTENT_TYPE)
            job.redacted_pdf_key = redacted_key
            session.add(job)
            await transition_job_status(session, job, JobStatus.VERIFIED)
            await session.commit()
        except Exception as exc:
            # Why: digest-only failure logging (no raw exception message/traceback) -- this
            # pipeline persists real detected PII (Span.text), and a future exception whose
            # message happens to echo detected content (e.g. a DB error echoing an offending
            # column value) must not leak raw PII into logs. Deliberately not
            # LOGGER.exception() -- that would attach the raw message/traceback via
            # exc_info=True, which is exactly what this must avoid.
            LOGGER.error(  # noqa: TRY400 - intentionally not .exception(): see comment above
                "apply_job_failed", extra={"job_id": job_id, "exception_type": type(exc).__name__}
            )
            await session.rollback()
            failed = await fail_job(UUID(job_id))
            if failed is not None:
                await log_job_terminal(failed, JobStatus.FAILED)
            raise

        await log_job_terminal(job, JobStatus.VERIFIED)
