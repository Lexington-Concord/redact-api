"""Redaction-job API surface: jobs -> spans -> dispositions -> apply -> export.

Six endpoints implementing redact-api#7. HTTP concerns live here; the state-machine
invariants (``transition_job_status``, audit hash chain) and the span projection /
disposition-batch orchestration live in the service layer. Exception-to-status mapping
is inline (documents.py precedent): state-conflict failures map to 409, content/shape
failures to 422, and a verify-gate FAIL at apply is a normal 422 (not an exception).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from sqlmodel import col, select

from redact_api.core.activity_logging import ActivityAction, log_activity_decorator
from redact_api.core.config import settings
from redact_api.core.permissions import RequireAdmin
from redact_api.core.tenants import TenantDep, add_tenant_filter
from redact_api.db.session import SessionDep
from redact_api.ingest.exceptions import (
    DocumentTooLargeError,
    EncryptedPdfError,
    MalformedPdfError,
    UnsupportedPageError,
)
from redact_api.ingest.service import ingest_pdf
from redact_api.models.document import Document
from redact_api.models.page import Page
from redact_api.models.redaction_job import JobStatus, RedactionJob, RedactionJobRead
from redact_api.models.span import Span, SpanRead
from redact_api.redaction.apply import apply
from redact_api.redaction.models import VerifyResult
from redact_api.services.jobs_service import (
    DispositionBatchRequest,
    DispositionBatchResult,
    SpanNotFoundError,
    apply_disposition_batch,
    project_approved_spans,
)
from redact_api.services.redaction_job_service import (
    InvalidStateTransitionError,
    UndispositionedSpansError,
    transition_job_status,
)
from redact_api.storage import keys
from redact_api.storage.dependency import StorageClientDep

router = APIRouter(prefix="/jobs", tags=["jobs"])

_PDF_CONTENT_TYPE = "application/pdf"


async def _get_job_or_404(session: SessionDep, tenant: TenantDep, job_id: UUID) -> RedactionJob:
    """Load a tenant-scoped job by id, raising 404 if absent or cross-tenant."""
    base_stmt = select(RedactionJob).where(col(RedactionJob.id) == job_id)
    stmt = add_tenant_filter(base_stmt, tenant, RedactionJob.organization_id)  # type: ignore[arg-type]
    job = (await session.execute(stmt)).scalar_one_or_none()
    if job is None:
        job_not_found_msg = "Redaction job not found"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=job_not_found_msg)
    return job


def _verify_failure_detail(verify_result: VerifyResult) -> dict[str, object]:
    """Build a digest-only 422 body for an apply-time verify FAIL (carries no raw PII)."""
    return {
        "message": "Redaction failed verification; job marked failed",
        "verdict": verify_result.verdict.value,
        "findings": [
            {
                "check_type": finding.check_type.value,
                "page_number": finding.page_number,
                "redacted_string_digest": finding.redacted_string_digest,
            }
            for finding in verify_result.findings
        ],
    }


@router.post("", response_model=RedactionJobRead, status_code=status.HTTP_201_CREATED)
@log_activity_decorator(ActivityAction.CREATE, "redaction_job")
async def create_job(
    session: SessionDep,
    tenant: TenantDep,
    storage: StorageClientDep,
    file: UploadFile = File(...),  # noqa: B008
) -> RedactionJobRead:
    """Upload a PDF, create its document + job, stage the original, and ingest synchronously.

    Creates ``Document`` + ``RedactionJob`` in one transaction, uploads the original PDF to
    object storage, runs ``ingest_pdf`` (which stages per-page artifacts), then walks the
    job UPLOADED -> INGESTED -> DETECTED -> IN_REVIEW. Ingest rejections map to 422; an
    over-limit upload is rejected at 413 before any work.
    """
    if not file.filename:
        missing_filename_msg = "File must have a filename"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=missing_filename_msg)

    content_type = file.content_type or "application/octet-stream"
    if content_type != _PDF_CONTENT_TYPE:
        unsupported_type_msg = "Only application/pdf uploads are supported"
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=unsupported_type_msg)

    pdf_bytes = await file.read(settings.max_file_size_bytes + 1)
    if len(pdf_bytes) > settings.max_file_size_bytes:
        max_mb = settings.max_file_size_bytes / 1024 / 1024
        too_large_msg = f"File exceeds maximum size of {max_mb:.1f}MB"
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=too_large_msg)

    document = Document(
        filename=file.filename,
        content_type=content_type,
        file_size=len(pdf_bytes),
        organization_id=tenant.organization_id,
        storage_path="",
        storage_url="",
    )
    session.add(document)
    await session.flush()  # type: ignore[attr-defined]  # assign document.id

    original_key = keys.original_pdf_key(document.id)
    document.storage_path = original_key
    document.storage_url = original_key
    session.add(document)

    job = RedactionJob(
        document_id=document.id,
        organization_id=tenant.organization_id,
        status=JobStatus.UPLOADED,
    )
    session.add(job)
    await session.flush()  # type: ignore[attr-defined]  # assign job.id

    # Why: ingest runs before the original is uploaded so a rejected PDF (oversized,
    # encrypted, malformed, unsupported page) never leaves an orphaned original blob in
    # storage with no committed DB row pointing at it -- ingest_pdf validates fully in
    # memory before it uploads anything of its own (see its docstring).
    try:
        await ingest_pdf(document.id, pdf_bytes, storage)
    except (DocumentTooLargeError, EncryptedPdfError, MalformedPdfError, UnsupportedPageError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=error.message) from error

    await storage.upload_bytes(original_key, pdf_bytes, content_type=_PDF_CONTENT_TYPE)

    await transition_job_status(session, job, JobStatus.INGESTED)
    await transition_job_status(session, job, JobStatus.DETECTED)
    await transition_job_status(session, job, JobStatus.IN_REVIEW)

    await session.commit()
    await session.refresh(job)
    return RedactionJobRead.model_validate(job)


@router.get("/{job_id}", response_model=RedactionJobRead)
@log_activity_decorator(ActivityAction.READ, "redaction_job", resource_id_param_name="job_id")
async def get_job(job_id: UUID, session: SessionDep, tenant: TenantDep) -> RedactionJobRead:
    """Fetch a single tenant-scoped redaction job."""
    job = await _get_job_or_404(session, tenant, job_id)
    return RedactionJobRead.model_validate(job)


@router.get("/{job_id}/spans", response_model=list[SpanRead])
@log_activity_decorator(ActivityAction.READ, "span", resource_id_param_name="job_id")
async def list_job_spans(job_id: UUID, session: SessionDep, tenant: TenantDep) -> list[SpanRead]:
    """List the spans for a job (job-scoped bounded set; deliberately not paginated)."""
    job = await _get_job_or_404(session, tenant, job_id)
    stmt = (
        select(Span)
        .join(Page, col(Span.page_id) == col(Page.id))
        .where(col(Page.document_id) == job.document_id)
        .order_by(col(Page.page_number), col(Span.id))
    )
    spans = (await session.execute(stmt)).scalars().all()
    return [SpanRead.model_validate(span) for span in spans]


@router.post("/{job_id}/dispositions", response_model=DispositionBatchResult)
@log_activity_decorator(ActivityAction.UPDATE, "disposition", resource_id_param_name="job_id")
async def create_dispositions(
    job_id: UUID,
    session: SessionDep,
    tenant: TenantDep,
    payload: DispositionBatchRequest,
) -> DispositionBatchResult:
    """Apply a batch of disposition verbs; reviewer identity is resolved from the tenant.

    Requires the job to be IN_REVIEW (409 otherwise). Re-disposition updates in place;
    an identical resubmission is an idempotent no-op. A referenced span that is not on the
    job's document yields 404.
    """
    job = await _get_job_or_404(session, tenant, job_id)
    if job.status is not JobStatus.IN_REVIEW:
        wrong_state_msg = f"Job is {job.status.value}; dispositions require in_review"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=wrong_state_msg)

    try:
        result = await apply_disposition_batch(session, job, payload.items, tenant.user_id)
    except SpanNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    await session.commit()
    return result


@router.post("/{job_id}/apply", response_model=RedactionJobRead)
@log_activity_decorator(ActivityAction.UPDATE, "redaction_job", resource_id_param_name="job_id")
async def apply_job(
    job_id: UUID,
    session: SessionDep,
    tenant: TenantDep,
    storage: StorageClientDep,
    role_check: RequireAdmin,
) -> RedactionJobRead:
    """Burn approved spans into the original PDF and gate the output through verify.

    ADMIN-only. Moves IN_REVIEW -> APPLYING (409 on a bad edge or undispositioned spans),
    downloads the original, projects approved spans (422 on a malformed bbox shape), runs
    ``apply``, and on PASS stores the redacted PDF and moves to VERIFIED. On a verify FAIL
    the job moves to FAILED and the endpoint returns 422 with a digest-only summary.
    """
    _ = role_check
    job = await _get_job_or_404(session, tenant, job_id)

    try:
        await transition_job_status(session, job, JobStatus.APPLYING)
    except (InvalidStateTransitionError, UndispositionedSpansError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    original_bytes = await storage.download_bytes(keys.original_pdf_key(job.document_id))
    approved_spans = await project_approved_spans(session, job)
    result = apply(original_bytes, approved_spans)

    if not result.passed:
        await transition_job_status(session, job, JobStatus.FAILED)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_verify_failure_detail(result.verify_result),
        )

    redacted_key = keys.redacted_pdf_key(job.id)
    await storage.upload_bytes(redacted_key, result.pdf_bytes, content_type=_PDF_CONTENT_TYPE)
    job.redacted_pdf_key = redacted_key
    session.add(job)
    await transition_job_status(session, job, JobStatus.VERIFIED)

    await session.commit()
    await session.refresh(job)
    return RedactionJobRead.model_validate(job)


@router.get("/{job_id}/export")
@log_activity_decorator(ActivityAction.READ, "redaction_job", resource_id_param_name="job_id")
async def export_job(
    job_id: UUID,
    session: SessionDep,
    tenant: TenantDep,
    storage: StorageClientDep,
    role_check: RequireAdmin,
) -> Response:
    """Stream the verified redacted PDF and move VERIFIED -> EXPORTED (idempotent re-read).

    ADMIN-only. A job earlier than VERIFIED yields 409; a VERIFIED or already-EXPORTED job
    returns the persisted redacted bytes (never recomputed). The VERIFIED -> EXPORTED
    transition happens once; re-reads of an EXPORTED job are served without re-transitioning.
    """
    _ = role_check
    job = await _get_job_or_404(session, tenant, job_id)

    if job.status not in (JobStatus.VERIFIED, JobStatus.EXPORTED):
        not_exportable_msg = f"Job is {job.status.value}; export requires a verified job"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=not_exportable_msg)
    if job.redacted_pdf_key is None:
        missing_artifact_msg = "Job has no redacted artifact to export"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=missing_artifact_msg)

    pdf_bytes = await storage.download_bytes(job.redacted_pdf_key)

    if job.status is JobStatus.VERIFIED:
        await transition_job_status(session, job, JobStatus.EXPORTED)
        await session.commit()

    return Response(content=pdf_bytes, media_type=_PDF_CONTENT_TYPE)
