"""Object storage abstraction layer with multiple provider support.

This module provides a unified interface for storing and retrieving files across
different storage backends (local filesystem, Azure Blob Storage, AWS S3, Google
Cloud Storage).

Architecture:
    - StorageService: Abstract base protocol defining the storage interface
    - StorageProvider: Enum of available storage backends
    - get_storage_service(): Factory function to instantiate the configured provider

Usage:
    from redact_api.core.storage import get_storage_service

    storage = get_storage_service()
    storage_url = await storage.upload(
        document_id=doc_id,
        file_data=file_bytes,
        content_type="application/pdf"
    )

Provider Configuration:
    Set STORAGE_PROVIDER environment variable to choose backend:
    - "local" (default): Store files in local filesystem (development)
    - "azure": Azure Blob Storage (requires azure-storage-blob)
    - "aws_s3": AWS S3 (requires aioboto3)
    - "gcs": Google Cloud Storage (requires google-cloud-storage)

    See core/config.py for provider-specific configuration options.

Migration Path:
    To migrate from local to cloud storage:
    1. Update STORAGE_PROVIDER in .env
    2. Configure provider-specific settings (container/bucket names, credentials)
    3. Install optional dependencies: pip install .[azure] or .[aws] or .[gcs]
    4. Restart application - new uploads use cloud storage
    5. Migrate existing files using a data migration script
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from redact_api.core.config import Settings

# Module-level settings reference (populated at import time after config is loaded)
settings: Settings | None = None


class StorageProvider(StrEnum):
    """Storage backend provider types.

    Attributes:
        LOCAL: Local filesystem storage (for development/testing)
        AZURE: Azure Blob Storage (production cloud storage)
        AWS_S3: AWS S3 (production cloud storage)
        GCS: Google Cloud Storage (production cloud storage)
    """

    LOCAL = "local"
    AZURE = "azure"
    AWS_S3 = "aws_s3"
    GCS = "gcs"


class StorageService(Protocol):
    """Abstract interface for file storage operations.

    All storage providers must implement these methods to ensure consistent
    behavior across different backends.

    Example implementation:
        class MyStorageService:
            async def upload(
                self,
                document_id: UUID,
                file_data: bytes,
                content_type: str,
                organization_id: UUID | None = None,
            ) -> str:
                # Upload logic here
                return storage_url
    """

    async def upload(
        self,
        document_id: UUID,
        file_data: bytes,
        content_type: str,
        organization_id: UUID | None = None,
    ) -> str:
        """Upload a file to storage.

        Args:
            document_id: Unique identifier for the document
            file_data: Binary file content
            content_type: MIME type (e.g., "application/pdf", "image/png")
            organization_id: Optional organization ID for multi-tenant isolation

        Returns:
            Storage URL or path where the file can be accessed

        Raises:
            StorageError: If upload fails due to network, permissions, or quota issues
        """
        ...

    async def download(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
    ) -> bytes | None:
        """Download a file from storage.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for multi-tenant isolation

        Returns:
            Binary file content, or None if file not found

        Raises:
            StorageError: If download fails due to network or permissions issues
        """
        ...

    async def delete(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
    ) -> bool:
        """Delete a file from storage.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for multi-tenant isolation

        Returns:
            True if file was deleted, False if file didn't exist

        Raises:
            StorageError: If deletion fails due to network or permissions issues
        """
        ...

    async def get_download_url(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
        expiry_seconds: int = 3600,
    ) -> str:
        """Generate a signed URL for direct file download.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for multi-tenant isolation
            expiry_seconds: URL validity duration in seconds (default: 1 hour)

        Returns:
            Signed URL for direct download (cloud) or local path (filesystem)

        Raises:
            StorageError: If URL generation fails
        """
        ...


class StorageError(Exception):
    """Base exception for storage operations.

    Raised when storage operations fail due to network issues, permission problems,
    quota limits, or other provider-specific errors.

    Example:
        try:
            await storage.upload(doc_id, file_data, "application/pdf")
        except StorageError as e:
            logger.error(f"Failed to upload document: {e}")
            raise HTTPException(status_code=503, detail="Storage service unavailable")
    """

    pass


def _get_local_storage() -> StorageService:
    """Create local filesystem storage service."""
    from redact_api.core.storage_providers import LocalStorageService

    return LocalStorageService(base_path=settings.storage_local_path)  # type: ignore[union-attr]


def _get_azure_storage() -> StorageService:
    """Create Azure Blob Storage service."""
    # Validate configuration before attempting import
    if (
        not settings.storage_azure_container  # type: ignore[union-attr]
        or not settings.storage_azure_connection_string  # type: ignore[union-attr]
    ):
        msg = (
            "Azure storage requires STORAGE_AZURE_CONTAINER and STORAGE_AZURE_CONNECTION_STRING environment variables"
        )
        raise ValueError(msg)

    try:
        # Use __import__ with fromlist to properly trigger mocks in tests
        __import__(
            "redact_api.core.storage_providers.AzureBlobStorageService",
            fromlist=["AzureBlobStorageService"],
        )
        from redact_api.core.storage_providers import (
            AzureBlobStorageService,
        )
    except ImportError as e:
        msg = "Azure Blob Storage requires 'azure-storage-blob' package. Install with: pip install .[azure]"
        raise ValueError(msg) from e

    return AzureBlobStorageService(
        container_name=settings.storage_azure_container,  # type: ignore[union-attr]
        connection_string=settings.storage_azure_connection_string,  # type: ignore[union-attr]
    )


def _get_s3_storage() -> StorageService:
    """Create AWS S3 storage service."""
    # Validate configuration before attempting import
    if not settings.storage_aws_bucket or not settings.storage_aws_region:  # type: ignore[union-attr]
        msg = "AWS S3 storage requires STORAGE_AWS_BUCKET and STORAGE_AWS_REGION environment variables"
        raise ValueError(msg)

    try:
        # Use __import__ with fromlist to properly trigger mocks in tests
        __import__(
            "redact_api.core.storage_providers.S3StorageService",
            fromlist=["S3StorageService"],
        )
        from redact_api.core.storage_providers import (
            S3StorageService,
        )
    except ImportError as e:
        msg = "AWS S3 requires 'aioboto3' package. Install with: pip install .[aws]"
        raise ValueError(msg) from e

    return S3StorageService(
        bucket_name=settings.storage_aws_bucket,  # type: ignore[union-attr]
        region=settings.storage_aws_region,  # type: ignore[union-attr]
    )


def _get_gcs_storage() -> StorageService:
    """Create Google Cloud Storage service."""
    # Validate configuration before attempting import
    if not settings.storage_gcs_bucket or not settings.storage_gcs_project_id:  # type: ignore[union-attr]
        msg = "GCS storage requires STORAGE_GCS_BUCKET and STORAGE_GCS_PROJECT_ID environment variables"
        raise ValueError(msg)

    try:
        # Use __import__ with fromlist to properly trigger mocks in tests
        __import__(
            "redact_api.core.storage_providers.GCSStorageService",
            fromlist=["GCSStorageService"],
        )
        from redact_api.core.storage_providers import (
            GCSStorageService,
        )
    except ImportError as e:
        msg = "Google Cloud Storage requires 'google-cloud-storage' package. Install with: pip install .[gcs]"
        raise ValueError(msg) from e

    return GCSStorageService(
        bucket_name=settings.storage_gcs_bucket,  # type: ignore[union-attr]
        project_id=settings.storage_gcs_project_id,  # type: ignore[union-attr]
    )


def get_storage_service() -> StorageService:
    """Factory function to create the configured storage service.

    Returns the appropriate storage service implementation based on
    STORAGE_PROVIDER environment variable.

    Returns:
        Configured StorageService instance

    Raises:
        ValueError: If STORAGE_PROVIDER is not recognized or required
                   dependencies are missing

    Example:
        storage = get_storage_service()
        url = await storage.upload(doc_id, file_bytes, "image/png")
    """
    # Ensure settings is initialized (handles circular imports)
    _init_settings()

    # Type guard for mypy (settings is always initialized by _init_settings)
    if settings is None:
        msg = "Settings not initialized"
        raise RuntimeError(msg)

    providers = {
        StorageProvider.LOCAL: _get_local_storage,
        StorageProvider.AZURE: _get_azure_storage,
        StorageProvider.AWS_S3: _get_s3_storage,
        StorageProvider.GCS: _get_gcs_storage,
    }

    provider_func = providers.get(settings.storage_provider)
    if provider_func:
        return provider_func()

    msg = f"Unrecognized storage provider: {settings.storage_provider}. Must be one of: {', '.join(StorageProvider)}"
    raise ValueError(msg)


# Initialize module-level settings reference when first accessed
def _init_settings() -> None:
    """Initialize module-level settings reference after config is loaded."""
    global settings  # noqa: PLW0603
    if settings is None:
        from redact_api.core.config import settings as _settings

        settings = _settings
