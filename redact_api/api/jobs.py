"""Redaction-job API surface: jobs -> spans -> dispositions -> apply -> export.

Six endpoints implementing redact-api#7. HTTP concerns live here; the state-machine
invariants (``transition_job_status``, audit hash chain) and the span projection /
disposition-batch orchestration live in the service layer. Exception-to-status mapping
is inline (documents.py precedent): state-conflict failures map to 409, content/shape
failures to 422, and a verify-gate FAIL at apply is a normal 422 (not an exception).
"""

from __future__ import annotations

import io
import zipfile
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
from redact_api.ingest.pdf import validate_pdf_structure
from redact_api.models.audit_entry import AuditAction
from redact_api.models.document import Document
from redact_api.models.page import Page
from redact_api.models.redaction_job import JobStatus, RedactionJob, RedactionJobRead
from redact_api.models.span import Span, SpanRead
from redact_api.services.export_manifest_service import (
    ExportAssemblyError,
    assemble_export_manifest,
)
from redact_api.services.jobs_service import (
    DispositionBatchRequest,
    DispositionBatchResult,
    SpanNotFoundError,
    apply_disposition_batch,
)
from redact_api.services.redaction_job_service import (
    JOB_LIFECYCLE_CATEGORY,
    AuditEntryInput,
    InvalidStateTransitionError,
    UndispositionedSpansError,
    append_audit_entry,
    transition_job_status,
    verify_audit_chain,
)
from redact_api.storage import keys
from redact_api.storage.dependency import StorageClientDep
from redact_api.tasks.apply_job import apply_job as apply_job_task
from redact_api.tasks.ingest_job import ingest_job as ingest_job_task

router = APIRouter(prefix="/jobs", tags=["jobs"])

_PDF_CONTENT_TYPE = "application/pdf"
_ZIP_CONTENT_TYPE = "application/zip"
_MANIFEST_CONTENT_TYPE = "application/json"
_EXPORT_PDF_MEMBER = "redacted.pdf"
_EXPORT_MANIFEST_MEMBER = "manifest.json"


async def _get_job_or_404(session: SessionDep, tenant: TenantDep, job_id: UUID) -> RedactionJob:
    """Load a tenant-scoped job by id, raising 404 if absent or cross-tenant."""
    base_stmt = select(RedactionJob).where(col(RedactionJob.id) == job_id)
    stmt = add_tenant_filter(base_stmt, tenant, RedactionJob.organization_id)  # type: ignore[arg-type]
    job = (await session.execute(stmt)).scalar_one_or_none()
    if job is None:
        job_not_found_msg = "Redaction job not found"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=job_not_found_msg)
    return job


@router.post("", response_model=RedactionJobRead, status_code=status.HTTP_201_CREATED)
@log_activity_decorator(ActivityAction.CREATE, "redaction_job")
async def create_job(
    session: SessionDep,
    tenant: TenantDep,
    storage: StorageClientDep,
    file: UploadFile = File(...),  # noqa: B008
) -> RedactionJobRead:
    """Upload a PDF, create its document + job, run the cheap structural pre-check, and enqueue ingest_job.

    Creates ``Document`` + ``RedactionJob`` in one transaction and stages the original PDF.
    ``validate_pdf_structure`` runs synchronously here (no rasterization) so a structurally
    invalid upload still fails fast with 422/413 before any async work is queued. The
    expensive path -- per-page artifact staging and detection -- now runs in ``ingest_job``
    (which chains into ``detect_job`` on success), enqueued after commit. The response
    reflects the job at UPLOADED; callers poll GET /jobs/{id} for status.
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

    # Fail fast on a structurally invalid upload before persisting or enqueuing anything --
    # same four ingest exceptions the async ingest_pdf path would raise, mapped to 422.
    try:
        validate_pdf_structure(pdf_bytes)
    except (DocumentTooLargeError, EncryptedPdfError, MalformedPdfError, UnsupportedPageError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=error.message) from error

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

    await storage.upload_bytes(original_key, pdf_bytes, content_type=_PDF_CONTENT_TYPE)

    await session.commit()
    await session.refresh(job)

    # Enqueue after commit so the worker observes the persisted UPLOADED job.
    await ingest_job_task.kiq(job_id=str(job.id))
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
    role_check: RequireAdmin,
) -> RedactionJobRead:
    """Move IN_REVIEW -> APPLYING and enqueue apply_job to burn approved spans and verify.

    ADMIN-only. Validates the IN_REVIEW -> APPLYING edge synchronously (409 on a bad edge or
    undispositioned spans) so a caller still gets immediate feedback on a wrong-state apply,
    then enqueues ``apply_job`` (job_id only) and returns the job at APPLYING. The burn-in
    and verify gate now run asynchronously; callers poll GET /jobs/{id} for the outcome (a
    verify FAIL is no longer visible synchronously on this response -- it surfaces as
    job.status == FAILED).
    """
    _ = role_check
    job = await _get_job_or_404(session, tenant, job_id)

    try:
        await transition_job_status(session, job, JobStatus.APPLYING)
    except (InvalidStateTransitionError, UndispositionedSpansError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    await session.commit()
    await session.refresh(job)

    # Enqueue after commit so the worker observes the persisted APPLYING job. reviewer_id is
    # threaded so the task-layer lifecycle audit entries attribute to the requesting reviewer.
    await apply_job_task.kiq(job_id=str(job.id), reviewer_id=str(tenant.user_id))
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
    """Return a zip of the verified redacted PDF + audit manifest, moving VERIFIED -> EXPORTED.

    ADMIN-only. A job earlier than VERIFIED yields 409. The audit hash chain is verified first;
    a broken chain yields 409 before any bytes are served. The response is an
    ``application/zip`` bundle of ``redacted.pdf`` (the persisted redacted bytes, never
    recomputed) plus ``manifest.json`` (the digest-only ``ExportManifest``). The manifest is
    assembled fresh from the live chain on every GET -- including re-reads of an already-EXPORTED
    job -- so it always reflects current chain state. The VERIFIED -> EXPORTED transition and its
    EXPORTED audit entry happen exactly once; re-reads of an EXPORTED job are served without
    re-transitioning or re-appending.
    """
    _ = role_check
    job = await _get_job_or_404(session, tenant, job_id)

    if job.status not in (JobStatus.VERIFIED, JobStatus.EXPORTED):
        not_exportable_msg = f"Job is {job.status.value}; export requires a verified job"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=not_exportable_msg)
    if job.redacted_pdf_key is None:
        missing_artifact_msg = "Job has no redacted artifact to export"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=missing_artifact_msg)

    # Gate on chain integrity before touching any PDF bytes: a tampered audit trail must not
    # yield an export bundle. The verified ChainVerifyResult is passed into
    # assemble_export_manifest below so it isn't recomputed a second time.
    chain = await verify_audit_chain(session, job.id)
    if not chain.verified:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "audit_chain_broken",
                "message": "Audit chain failed verification; export blocked",
                "entry_count": chain.entry_count,
                "first_broken_entry_id": str(chain.first_broken_entry_id)
                if chain.first_broken_entry_id is not None
                else None,
            },
        )

    # Downloaded once here (after the chain gate) and reused for both hashing (inside
    # assemble_export_manifest) and the zip bundle below, instead of fetching the same object twice.
    pdf_bytes = await storage.download_bytes(job.redacted_pdf_key)

    try:
        manifest = await assemble_export_manifest(session, storage, job, chain=chain, redacted_bytes=pdf_bytes)
    except ExportAssemblyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "export_assembly_failed", "message": str(error)},
        ) from error

    manifest_bytes = manifest.model_dump_json().encode("utf-8")
    zip_bytes = _build_export_zip(pdf_bytes, manifest_bytes)
    # Persist the canonical manifest alongside the redacted artifact (idempotent overwrite).
    await storage.upload_bytes(keys.export_manifest_key(job.id), manifest_bytes, content_type=_MANIFEST_CONTENT_TYPE)

    if job.status is JobStatus.VERIFIED:
        # EXPORTED audit entry + transition fire exactly once, only on the first export; the
        # manifest above was assembled before this row exists, so a first-export manifest never
        # lists its own EXPORTED event.
        await append_audit_entry(
            session,
            job.id,
            AuditEntryInput(
                action=AuditAction.EXPORTED,
                category=JOB_LIFECYCLE_CATEGORY,
                text=None,
                reviewer_id=tenant.user_id,
            ),
        )
        await transition_job_status(session, job, JobStatus.EXPORTED)
        await session.commit()

    return Response(
        content=zip_bytes,
        media_type=_ZIP_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="job-{job_id}-export.zip"'},
    )


def _build_export_zip(pdf_bytes: bytes, manifest_bytes: bytes) -> bytes:
    """Bundle the redacted PDF and manifest JSON into an in-memory zip archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_EXPORT_PDF_MEMBER, pdf_bytes)
        archive.writestr(_EXPORT_MANIFEST_MEMBER, manifest_bytes)
    return buffer.getvalue()
