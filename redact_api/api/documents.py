"""Document upload and download endpoints with object storage.

This module provides API endpoints for uploading and downloading documents
using object storage (local filesystem, Azure Blob, AWS S3, or GCS).

Files are stored in object storage rather than the database, providing:
- Scalability: Files don't bloat the database
- Performance: Faster queries without large binary data
- Cost efficiency: Object storage is cheaper than database storage

Security Note:
    All document endpoints enforce tenant isolation via TenantDep.
    Documents are scoped to organization_id and users can only access
    documents belonging to their organization.

Architecture:
    1. Upload endpoint receives file via multipart/form-data
    2. File is uploaded to object storage via StorageService
    3. Document metadata (filename, size, storage_path, storage_url) saved to DB
    4. Download endpoint retrieves file from object storage and streams to client

For cloud providers (Azure/S3/GCS), the download endpoint returns a redirect
to a presigned URL for direct download, reducing load on the application server.
"""

import time
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlmodel import col

from redact_api.core.activity_logging import ActivityAction, log_activity_decorator
from redact_api.core.config import settings
from redact_api.core.metrics import (
    database_query_duration_seconds,
    document_upload_size_bytes,
)
from redact_api.core.storage import (
    StorageError,
    StorageProvider,
    StorageService,
    get_storage_service,
)
from redact_api.core.tenants import TenantDep, add_tenant_filter
from redact_api.db.session import SessionDep
from redact_api.models.document import Document, DocumentRead

router = APIRouter(prefix="/documents", tags=["documents"])

# Dependency to get storage service (allows for testing/mocking)
StorageServiceDep = Annotated[StorageService, Depends(get_storage_service)]

# MIME type validation constants
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/json",
    "image/jpeg",
    "image/png",
    "image/gif",
    "text/plain",
    "application/zip",
}

DANGEROUS_MIME_TYPES = {
    "text/html",
    "image/svg+xml",
    "application/javascript",
    "text/javascript",
}


def iter_file_chunks(data: bytes, chunk_size: int = 8192) -> Iterator[bytes]:
    """Yield chunks of binary data for streaming.

    Args:
        data: Binary data to stream
        chunk_size: Size of each chunk in bytes (default 8KB)

    Yields:
        Chunks of binary data
    """
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
@log_activity_decorator(ActivityAction.CREATE, "document")
async def upload_document(
    session: SessionDep,
    tenant: TenantDep,
    storage_service: StorageServiceDep,
    file: UploadFile = File(...),  # noqa: B008
) -> DocumentRead:
    """Upload a file to object storage and save metadata to database.

    The file is uploaded to the configured storage provider (local, Azure, S3, GCS)
    and metadata is saved to the database. The response includes a storage_url
    that can be used to download the file.

    Security Note:
        Document is automatically scoped to tenant.organization_id.
        User can only create documents in their own organization.
        Files are stored in object storage under organization_id for tenant isolation.

    Args:
        session: Database session
        tenant: Tenant context with organization_id
        storage_service: Storage service for file operations
        file: Uploaded file from multipart/form-data

    Returns:
        Document metadata including storage_url for download

    Raises:
        HTTPException: If file validation fails or storage operation fails
    """
    if not file.filename:
        missing_filename_msg = "File must have a filename"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=missing_filename_msg,
        )

    # Validate MIME type for security
    content_type = file.content_type or "application/octet-stream"

    if content_type in DANGEROUS_MIME_TYPES:
        dangerous_type_msg = f"File type '{content_type}' not allowed for security reasons"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=dangerous_type_msg,
        )

    if content_type not in ALLOWED_MIME_TYPES:
        # Force to octet-stream for unknown types
        content_type = "application/octet-stream"

    # Read with size limit (+1 to detect oversized files)
    file_data = await file.read(settings.max_file_size_bytes + 1)
    file_size = len(file_data)

    if file_size > settings.max_file_size_bytes:
        max_mb = settings.max_file_size_bytes / 1024 / 1024
        file_too_large_msg = f"File exceeds maximum size of {max_mb:.1f}MB"
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=file_too_large_msg,
        )

    # Record document upload size metric
    document_upload_size_bytes.observe(file_size)

    # Create document record first to get UUID
    document = Document(
        filename=file.filename,
        content_type=content_type,  # Use sanitized content_type
        file_size=file_size,
        storage_path="",  # Will be updated after upload
        storage_url="",  # Will be updated after upload
        organization_id=tenant.organization_id,
    )

    session.add(document)
    await session.flush()  # type: ignore[attr-defined]  # Get document.id without committing

    # After flush, UUID should be assigned by database
    if document.id is None:
        document_id_error_msg = "Document ID not assigned after flush"
        raise RuntimeError(document_id_error_msg)

    # Upload to object storage with organization_id for tenant isolation
    try:
        storage_url = await storage_service.upload(
            document_id=document.id,
            file_data=file_data,
            content_type=content_type,  # Use sanitized content_type
            organization_id=tenant.organization_id,
        )
        document.storage_path = storage_url  # For local, path == url
        document.storage_url = storage_url
    except StorageError as e:
        await session.rollback()
        storage_upload_failed_msg = f"Failed to upload file to storage: {e}"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=storage_upload_failed_msg,
        ) from e

    await session.commit()
    await session.refresh(document)

    return DocumentRead.model_validate(document)


@router.get("/{document_id}", response_model=None)
@log_activity_decorator(ActivityAction.READ, "document")
async def download_document(
    document_id: UUID,
    session: SessionDep,
    tenant: TenantDep,
    storage_service: StorageServiceDep,
) -> StreamingResponse | RedirectResponse:
    """Download a document from object storage.

    For cloud providers (Azure/S3/GCS), this endpoint returns a redirect to a
    presigned URL for direct download, reducing load on the application server.

    For local storage, this endpoint streams the file content directly.

    Records database query duration metric for the document fetch operation.

    Security Note:
        Query is scoped to tenant.organization_id to prevent cross-tenant access.
        User can only download documents from their own organization.

    Args:
        document_id: UUID of the document to download
        session: Database session
        tenant: Tenant context with organization_id
        storage_service: Storage service for file operations

    Returns:
        StreamingResponse (local storage) or RedirectResponse (cloud storage)

    Raises:
        HTTPException: If document not found, doesn't belong to tenant's org,
                      or storage operation fails
    """
    # Record query duration for document fetch
    start = time.perf_counter()
    stmt = select(Document).where(col(Document.id) == document_id)
    # Apply tenant filter to prevent cross-tenant access
    stmt = add_tenant_filter(
        stmt,
        tenant,
        Document.organization_id,  # type: ignore[arg-type]
    )

    result = await session.execute(stmt)
    document = result.scalar_one_or_none()
    duration = time.perf_counter() - start
    database_query_duration_seconds.labels(query_type="select").observe(duration)

    if not document:
        document_not_found_msg = "Document not found"
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=document_not_found_msg,
        )

    # For cloud providers, redirect to presigned URL (offload bandwidth to cloud)
    if settings.storage_provider in (
        StorageProvider.AZURE,
        StorageProvider.AWS_S3,
        StorageProvider.GCS,
    ):
        try:
            download_url = await storage_service.get_download_url(
                document_id=document.id,
                organization_id=document.organization_id,
                expiry_seconds=3600,  # 1 hour expiry
            )
            return RedirectResponse(url=download_url, status_code=status.HTTP_302_FOUND)
        except StorageError as e:
            storage_download_failed_msg = f"Failed to generate download URL: {e}"
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=storage_download_failed_msg,
            ) from e

    # For local storage, stream file content directly
    try:
        file_data = await storage_service.download(
            document_id=document.id,
            organization_id=document.organization_id,
        )
        if file_data is None:
            file_not_found_in_storage_msg = "File not found in storage (metadata exists but file is missing)"
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=file_not_found_in_storage_msg,
            )

        return StreamingResponse(
            iter_file_chunks(file_data),
            media_type=document.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{document.filename}"',
            },
        )
    except StorageError as e:
        storage_stream_failed_msg = f"Failed to download file from storage: {e}"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=storage_stream_failed_msg,
        ) from e


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
@log_activity_decorator(ActivityAction.DELETE, "document", resource_id_param_name="document_id")
async def delete_document(
    document_id: UUID,
    session: SessionDep,
    tenant: TenantDep,
    storage_service: StorageServiceDep,
) -> None:
    """Delete a document from both database and object storage.

    This endpoint performs a cascading delete:
    1. Verify document belongs to tenant's organization
    2. Delete file from object storage
    3. Delete metadata from database

    If storage deletion fails, the operation is rolled back to maintain consistency.

    Security Note:
        Query is scoped to tenant.organization_id to prevent cross-tenant access.
        User can only delete documents from their own organization.

    Args:
        document_id: UUID of the document to delete
        session: Database session
        tenant: Tenant context with organization_id
        storage_service: Storage service for file operations

    Raises:
        HTTPException: If document not found, doesn't belong to tenant's org,
                      or storage operation fails
    """
    # Fetch document with tenant filter
    stmt = select(Document).where(col(Document.id) == document_id)
    stmt = add_tenant_filter(
        stmt,
        tenant,
        Document.organization_id,  # type: ignore[arg-type]
    )

    result = await session.execute(stmt)
    document = result.scalar_one_or_none()

    if not document:
        document_not_found_msg = "Document not found"
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=document_not_found_msg,
        )

    # Delete from object storage first
    try:
        await storage_service.delete(
            document_id=document.id,
            organization_id=document.organization_id,
        )
    except StorageError as e:
        storage_delete_failed_msg = f"Failed to delete file from storage: {e}"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=storage_delete_failed_msg,
        ) from e

    # Delete from database
    await session.delete(document)
    await session.commit()
