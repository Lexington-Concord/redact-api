"""Document table for object storage with cloud provider support.

Documents are stored in object storage (local filesystem, Azure Blob Storage,
AWS S3, or Google Cloud Storage) rather than in the database.

This provides:
- Scalability: Files don't bloat the database
- Performance: Faster database queries without large binary data
- Cost efficiency: Object storage is cheaper than database storage
- Flexibility: Easy to switch between providers (local dev -> cloud production)

Migration from database storage:
    1. Update STORAGE_PROVIDER in .env (local, azure, aws_s3, gcs)
    2. Configure provider-specific settings (container/bucket, credentials)
    3. New uploads automatically use object storage
    4. Migrate existing file_data blobs to object storage with migration script

For provider setup instructions, see:
    - redact_api/core/storage.py (abstraction layer)
    - redact_api/core/storage_providers.py (implementation details)
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

import sqlalchemy as sa
from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

from redact_api.models.base import TimestampedTable


class DocumentBase(SQLModel):
    """Shared document metadata fields."""

    filename: str
    content_type: str
    file_size: int
    organization_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        )
    )


class Document(TimestampedTable, DocumentBase, table=True):
    """Document table with object storage references.

    Files are stored in object storage (not in database). Each document
    record contains:
    - Metadata: filename, content_type, file_size
    - Storage reference: storage_path (where file is stored)
    - Access URL: storage_url (for direct download, may be presigned)
    - Tenant isolation: organization_id (for multi-tenant security)

    The storage_path format varies by provider:
    - Local: ./uploads/{organization_id}/{document_id}
    - Azure: {organization_id}/{document_id} (blob name)
    - S3: {organization_id}/{document_id} (object key)
    - GCS: {organization_id}/{document_id} (blob name)

    The storage_url is provider-specific:
    - Local: Local file path (API streams content)
    - Azure: Signed URL with expiration (direct download)
    - S3: Presigned URL with expiration (direct download)
    - GCS: Signed URL with expiration (direct download)

    Security Note:
        Documents are tenant-isolated via organization_id foreign key.
        All queries MUST filter by organization_id to prevent cross-tenant access.
    """

    __tablename__ = "document"

    storage_path: str = Field(description="Storage path/key where file is stored in object storage")
    storage_url: str = Field(description="URL for accessing the file (may be presigned/temporary)")

    __table_args__ = (sa.Index("ix_document_organization_id", "organization_id"),)


class DocumentCreate(SQLModel):
    """Schema for creating a document.

    Note: file_data is NOT stored in this schema. It's passed separately
    via UploadFile in the API endpoint, uploaded to object storage, and
    only the metadata is saved to the database.
    """

    filename: str
    content_type: str
    file_size: int


class DocumentRead(DocumentBase):
    """Schema for reading document metadata.

    Returns metadata and storage URL for accessing the file.
    For cloud providers (Azure/S3/GCS), storage_url is a presigned URL
    that can be used directly. For local storage, use the download endpoint.
    """

    id: UUID
    storage_url: str
    created_at: datetime
    updated_at: datetime

    # SQLModel expects SQLModelConfig but accepts ConfigDict at runtime
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)  # type: ignore[assignment]
