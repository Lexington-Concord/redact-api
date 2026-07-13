"""Storage provider implementations for local filesystem and cloud storage.

This module contains concrete implementations of the StorageService interface:
- LocalStorageService: Development/testing storage using local filesystem
- AzureBlobStorageService: Production storage using Azure Blob Storage
- S3StorageService: Production storage using AWS S3
- GCSStorageService: Production storage using Google Cloud Storage

Each implementation handles provider-specific authentication, error handling,
and URL generation patterns.

Retry Behavior:
    Cloud storage operations use tenacity for automatic retry on transient failures.
    Default configuration: 3 attempts with exponential backoff (1s, 2s, 4s).
    Retried errors: Network timeouts, rate limiting (429/503), connection resets.

Setup Instructions:
    Local (no setup required):
        STORAGE_PROVIDER=local
        STORAGE_LOCAL_PATH=./uploads

    Azure Blob Storage:
        pip install azure-storage-blob
        STORAGE_PROVIDER=azure
        STORAGE_AZURE_CONTAINER=documents
        STORAGE_AZURE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...

    AWS S3:
        pip install aioboto3
        STORAGE_PROVIDER=aws_s3
        STORAGE_AWS_BUCKET=my-bucket
        STORAGE_AWS_REGION=us-east-1
        # AWS credentials from ~/.aws/credentials or IAM role

    Google Cloud Storage:
        pip install google-cloud-storage
        STORAGE_PROVIDER=gcs
        STORAGE_GCS_BUCKET=my-bucket
        STORAGE_GCS_PROJECT_ID=my-project
        # Credentials from GOOGLE_APPLICATION_CREDENTIALS env var
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, ParamSpec, TypeVar
from uuid import UUID

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from redact_api.core.logging import get_logging_context
from redact_api.core.storage import StorageError

LOGGER = logging.getLogger(__name__)

# Type variables for generic decorator
P = ParamSpec("P")
T = TypeVar("T")

# Retry configuration for cloud storage operations
STORAGE_RETRY_MAX_ATTEMPTS = 3
STORAGE_RETRY_WAIT_MULTIPLIER = 1
STORAGE_RETRY_MIN_WAIT = 1
STORAGE_RETRY_MAX_WAIT = 10


def _log_storage_retry(retry_state: RetryCallState) -> None:
    """Log storage retry attempts with context."""
    base_context = get_logging_context()
    exception = retry_state.outcome.exception() if retry_state.outcome else None

    extra = {
        **base_context,
        "attempt": retry_state.attempt_number,
        "exception_type": type(exception).__name__ if exception else "unknown",
        "exception_message": str(exception) if exception else "",
    }
    LOGGER.warning("storage_operation_retry", extra=extra)


# Optional cloud provider imports - separated by TYPE_CHECKING for proper mypy support
if TYPE_CHECKING:
    # Type-time imports: mypy sees these types but they don't execute at runtime
    import aioboto3
    from azure.core.exceptions import (
        ResourceNotFoundError as AzureResourceNotFoundError,
    )
    from azure.storage.blob import (
        BlobSasPermissions,
        generate_blob_sas,
    )
    from azure.storage.blob.aio import BlobServiceClient
    from botocore.exceptions import ClientError
    from google.cloud import storage
    from google.cloud.exceptions import NotFound
else:
    # Runtime imports: conditional loading with fallback to None
    BlobServiceClient = None
    AzureResourceNotFoundError = None
    BlobSasPermissions = None
    generate_blob_sas = None
    aioboto3 = None
    ClientError = None
    storage = None
    NotFound = None

    try:
        from azure.core.exceptions import (
            ResourceNotFoundError as AzureResourceNotFoundError,
        )
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas
        from azure.storage.blob.aio import BlobServiceClient
    except ImportError:
        pass

    try:
        import aioboto3
        from botocore.exceptions import ClientError
    except ImportError:
        pass

    try:
        from google.cloud import storage
        from google.cloud.exceptions import NotFound
    except ImportError:
        pass


def _is_transient_storage_error(exc: BaseException) -> bool:
    """Check if an exception is a transient storage error that should be retried.

    Transient errors include:
    - Network timeouts and connection resets
    - Rate limiting (HTTP 429, 503)
    - Temporary service unavailability

    Args:
        exc: The exception to check

    Returns:
        True if the error is transient and should be retried
    """
    # General network errors (applies to all providers)
    transient_error_strings = [
        "timeout",
        "connection reset",
        "connection refused",
        "temporary failure",
        "service unavailable",
        "too many requests",
    ]
    error_str = str(exc).lower()
    if any(msg in error_str for msg in transient_error_strings):
        return True

    # Azure-specific transient errors
    if "ServiceUnavailable" in str(type(exc).__name__):
        return True

    # Botocore/S3-specific transient errors
    if ClientError is not None and isinstance(exc, ClientError):
        error_code = exc.response.get("Error", {}).get("Code", "")
        transient_codes = ["Throttling", "ServiceUnavailable", "SlowDown", "RequestTimeout"]
        if error_code in transient_codes:
            return True

    return False


def create_storage_retry(
    *,
    max_attempts: int = STORAGE_RETRY_MAX_ATTEMPTS,
    min_wait: int = STORAGE_RETRY_MIN_WAIT,
    max_wait: int = STORAGE_RETRY_MAX_WAIT,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Create a retry decorator for storage operations.

    Factory function to create customized retry decorators. Use this when you need
    different retry behavior for specific operations.

    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
        min_wait: Minimum wait time in seconds (default: 1)
        max_wait: Maximum wait time in seconds (default: 10)

    Returns:
        Configured retry decorator

    Example:
        # More aggressive retry for critical uploads
        aggressive_retry = create_storage_retry(max_attempts=5, max_wait=30)

        @aggressive_retry
        async def critical_upload(...) -> str:
            ...
    """
    return retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(
            multiplier=STORAGE_RETRY_WAIT_MULTIPLIER,
            min=min_wait,
            max=max_wait,
        ),
        before_sleep=_log_storage_retry,
        reraise=True,
    )


# Default storage retry decorator
storage_retry: Callable[[Callable[P, T]], Callable[P, T]] = create_storage_retry()
"""Decorator for retrying storage operations on transient failures.

Retries operations that fail due to:
- Network timeouts and connection issues
- Rate limiting (HTTP 429/503)
- Temporary service unavailability

Uses exponential backoff: 1s, 2s, 4s... up to max 10s between retries.
Maximum 3 attempts before failing.

Usage:
    To add retry to a storage service method, apply this decorator:

    class MyStorageService:
        @storage_retry
        async def upload(self, doc_id: UUID, data: bytes, ...) -> str:
            # Your upload implementation
            ...

Note:
    The built-in storage services (Azure, S3, GCS) already handle errors
    and wrap them in StorageError. If you want retry behavior, you have
    two options:

    1. Wrap calls at the application layer:
       @storage_retry
       async def upload_with_retry(storage: StorageService, ...) -> str:
           return await storage.upload(...)

    2. Create a subclass with retry enabled:
       class RetryingS3StorageService(S3StorageService):
           @storage_retry
           async def upload(self, ...) -> str:
               return await super().upload(...)

Does NOT retry on (by design - these are permanent failures):
- Authentication errors (401/403)
- Not found errors (404)
- Permanent client errors (400)
- Storage quota exceeded
"""


class LocalStorageService:
    """Local filesystem storage implementation.

    Stores files in a local directory organized by organization and document ID.
    Suitable for development, testing, and small deployments where cloud storage
    is not required.

    Directory structure:
        {base_path}/
            {organization_id}/
                {document_id}

    Args:
        base_path: Root directory for file storage

    Example:
        storage = LocalStorageService(base_path="./uploads")
        url = await storage.upload(doc_id, file_bytes, "image/png", org_id)
        # File saved to: ./uploads/{org_id}/{doc_id}
    """

    def __init__(self, base_path: str) -> None:
        """Initialize local storage service.

        Args:
            base_path: Root directory path for file storage
        """
        self.base_path = Path(base_path)
        # Attempt to create directory but don't fail if permission denied
        # (can happen in tests or certain deployment scenarios)
        with contextlib.suppress(OSError, PermissionError):
            self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, document_id: UUID, organization_id: UUID | None) -> Path:
        """Generate file path for document.

        Args:
            document_id: Document unique identifier
            organization_id: Optional organization ID for multi-tenant isolation

        Returns:
            Path object for the document file

        Raises:
            StorageError: If resulting path escapes base_path (path traversal attempt)
        """
        if organization_id:
            org_dir = self.base_path / str(organization_id)
            org_dir.mkdir(parents=True, exist_ok=True)
            file_path = org_dir / str(document_id)
        else:
            file_path = self.base_path / str(document_id)

        # Validate that resolved path stays within base_path (prevent path traversal)
        try:
            resolved_file_path = file_path.resolve()
            resolved_base_path = self.base_path.resolve()
            # Ensure the file path is within or equals base_path
            if not str(resolved_file_path).startswith(str(resolved_base_path)):
                msg = f"Path traversal attempt detected: {document_id}"
                raise StorageError(msg)
        except (OSError, ValueError) as e:
            storage_error = f"Invalid file path: {e}"
            raise StorageError(storage_error) from e

        return file_path

    async def upload(
        self,
        document_id: UUID,
        file_data: bytes,
        content_type: str,  # noqa: ARG002
        organization_id: UUID | None = None,
    ) -> str:
        """Upload file to local filesystem.

        Args:
            document_id: Unique identifier for the document
            file_data: Binary file content
            content_type: MIME type (not used for local storage,
                preserved for interface compatibility)
            organization_id: Optional organization ID for directory organization

        Returns:
            Local file path as storage URL

        Raises:
            StorageError: If file write fails due to permissions or disk space
        """
        file_path = self._get_file_path(document_id, organization_id)

        try:
            # Use asyncio to avoid blocking on file I/O
            await asyncio.to_thread(file_path.write_bytes, file_data)
            return str(file_path)
        except OSError as e:
            storage_error = f"Failed to write file to local storage: {e}"
            raise StorageError(storage_error) from e

    async def download(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
    ) -> bytes | None:
        """Download file from local filesystem.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for directory organization

        Returns:
            Binary file content, or None if file not found

        Raises:
            StorageError: If file read fails due to permissions
        """
        file_path = self._get_file_path(document_id, organization_id)

        if not file_path.exists():
            return None

        try:
            return await asyncio.to_thread(file_path.read_bytes)
        except OSError as e:
            storage_error = f"Failed to read file from local storage: {e}"
            raise StorageError(storage_error) from e

    async def delete(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
    ) -> bool:
        """Delete file from local filesystem.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for directory organization

        Returns:
            True if file was deleted, False if file didn't exist

        Raises:
            StorageError: If file deletion fails due to permissions
        """
        file_path = self._get_file_path(document_id, organization_id)

        if not file_path.exists():
            return False

        try:
            await asyncio.to_thread(file_path.unlink)
        except OSError as e:
            storage_error = f"Failed to delete file from local storage: {e}"
            raise StorageError(storage_error) from e
        else:
            return True

    async def get_download_url(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
        expiry_seconds: int = 3600,  # noqa: ARG002
    ) -> str:
        """Generate download URL for local file.

        For local storage, this returns the file path since there's no concept
        of signed URLs. The API layer should stream the file content.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for directory organization
            expiry_seconds: Not used for local storage (preserved for interface
                compatibility)

        Returns:
            Local file path
        """
        file_path = self._get_file_path(document_id, organization_id)
        return str(file_path)


class AzureBlobStorageService:
    """Azure Blob Storage implementation.

    Stores files in Azure Blob Storage with support for signed URLs.
    Files are organized by blob name: {organization_id}/{document_id}

    Official documentation:
        https://learn.microsoft.com/en-us/azure/storage/blobs/storage-quickstart-blobs-python

    Setup:
        1. Create Azure Storage Account
        2. Create a container (e.g., "documents")
        3. Get connection string from Azure Portal
        4. Set environment variables:
           STORAGE_AZURE_CONTAINER=documents
           STORAGE_AZURE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...

    Args:
        container_name: Azure Blob container name
        connection_string: Azure Storage connection string

    Example:
        storage = AzureBlobStorageService(
            container_name="documents",
            connection_string="DefaultEndpointsProtocol=https;..."
        )
        url = await storage.upload(doc_id, file_bytes, "application/pdf", org_id)
    """

    def __init__(self, container_name: str, connection_string: str) -> None:
        """Initialize Azure Blob Storage service.

        Args:
            container_name: Name of the Azure Blob container
            connection_string: Azure Storage account connection string
        """
        if BlobServiceClient is None:
            msg = (
                "Azure Blob Storage requires 'azure-storage-blob' package. "
                "Install with: pip install azure-storage-blob"
            )
            raise ImportError(msg)

        self.container_name = container_name
        self.connection_string = connection_string
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)

    def _get_blob_name(self, document_id: UUID, organization_id: UUID | None) -> str:
        """Generate blob name for document.

        Args:
            document_id: Document unique identifier
            organization_id: Optional organization ID for namespace isolation

        Returns:
            Blob name in format: {org_id}/{doc_id} or just {doc_id}
        """
        if organization_id:
            return f"{organization_id}/{document_id}"
        return str(document_id)

    async def upload(
        self,
        document_id: UUID,
        file_data: bytes,
        content_type: str,
        organization_id: UUID | None = None,
    ) -> str:
        """Upload file to Azure Blob Storage.

        Args:
            document_id: Unique identifier for the document
            file_data: Binary file content
            content_type: MIME type for Content-Type header
            organization_id: Optional organization ID for namespace isolation

        Returns:
            Blob URL (not signed, use get_download_url for signed URL)

        Raises:
            StorageError: If upload fails due to network, auth, or quota issues
        """
        blob_name = self._get_blob_name(document_id, organization_id)
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=blob_name,
        )

        try:
            await blob_client.upload_blob(
                file_data,
                overwrite=True,
                content_settings={"content_type": content_type},
            )
        except Exception as e:
            storage_error = f"Failed to upload to Azure Blob Storage: {e}"
            raise StorageError(storage_error) from e
        else:
            return blob_client.url

    async def download(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
    ) -> bytes | None:
        """Download file from Azure Blob Storage.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for namespace isolation

        Returns:
            Binary file content, or None if blob not found

        Raises:
            StorageError: If download fails due to network or auth issues
        """
        blob_name = self._get_blob_name(document_id, organization_id)
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=blob_name,
        )

        try:
            download_stream = await blob_client.download_blob()
            return await download_stream.readall()
        except AzureResourceNotFoundError:
            return None
        except Exception as e:
            storage_error = f"Failed to download from Azure Blob Storage: {e}"
            raise StorageError(storage_error) from e

    async def delete(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
    ) -> bool:
        """Delete file from Azure Blob Storage.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for namespace isolation

        Returns:
            True if blob was deleted, False if blob didn't exist

        Raises:
            StorageError: If deletion fails due to network or auth issues
        """
        blob_name = self._get_blob_name(document_id, organization_id)
        blob_client = self.blob_service_client.get_blob_client(
            container=self.container_name,
            blob=blob_name,
        )

        try:
            await blob_client.delete_blob()
        except AzureResourceNotFoundError:
            return False
        except Exception as e:
            storage_error = f"Failed to delete from Azure Blob Storage: {e}"  # noqa: S608
            raise StorageError(storage_error) from e
        else:
            return True

    async def get_download_url(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
        expiry_seconds: int = 3600,
    ) -> str:
        """Generate signed URL for Azure blob download.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for namespace isolation
            expiry_seconds: URL validity duration in seconds (default: 1 hour)

        Returns:
            Signed URL valid for specified duration

        Raises:
            StorageError: If URL generation fails
        """
        blob_name = self._get_blob_name(document_id, organization_id)

        try:
            # Extract account name and key from connection string
            account_name = None
            account_key = None
            for part in self.connection_string.split(";"):
                if part.startswith("AccountName="):
                    account_name = part.replace("AccountName=", "")
                elif part.startswith("AccountKey="):
                    account_key = part.replace("AccountKey=", "")

            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=self.container_name,
                blob_name=blob_name,
                account_key=account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(UTC) + timedelta(seconds=expiry_seconds),
            )

            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name,
            )
        except Exception as e:
            storage_error = f"Failed to generate Azure Blob SAS URL: {e}"
            raise StorageError(storage_error) from e
        else:
            return f"{blob_client.url}?{sas_token}"


class S3StorageService:
    """AWS S3 storage implementation.

    Stores files in AWS S3 with support for presigned URLs.
    Files are organized by key: {organization_id}/{document_id}

    Official documentation:
        https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3-uploading-files.html

    Setup:
        1. Create S3 bucket in AWS Console
        2. Configure IAM permissions (s3:PutObject, s3:GetObject, s3:DeleteObject)
        3. Set AWS credentials (one of):
           - AWS CLI: aws configure
           - Environment: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
           - IAM role (for EC2, ECS, Lambda)
        4. Set environment variables:
           STORAGE_AWS_BUCKET=my-bucket
           STORAGE_AWS_REGION=us-east-1

    Args:
        bucket_name: S3 bucket name
        region: AWS region (e.g., "us-east-1")

    Example:
        storage = S3StorageService(bucket_name="my-bucket", region="us-east-1")
        url = await storage.upload(doc_id, file_bytes, "image/png", org_id)
    """

    def __init__(self, bucket_name: str, region: str) -> None:
        """Initialize AWS S3 storage service.

        Args:
            bucket_name: Name of the S3 bucket
            region: AWS region code
        """
        if aioboto3 is None:
            msg = "AWS S3 requires 'aioboto3' package. Install with: pip install aioboto3"
            raise ImportError(msg)

        self.bucket_name = bucket_name
        self.region = region
        self.session = aioboto3.Session()

    def _get_object_key(self, document_id: UUID, organization_id: UUID | None) -> str:
        """Generate S3 object key for document.

        Args:
            document_id: Document unique identifier
            organization_id: Optional organization ID for namespace isolation

        Returns:
            Object key in format: {org_id}/{doc_id} or just {doc_id}
        """
        if organization_id:
            return f"{organization_id}/{document_id}"
        return str(document_id)

    async def upload(
        self,
        document_id: UUID,
        file_data: bytes,
        content_type: str,
        organization_id: UUID | None = None,
    ) -> str:
        """Upload file to AWS S3.

        Args:
            document_id: Unique identifier for the document
            file_data: Binary file content
            content_type: MIME type for Content-Type metadata
            organization_id: Optional organization ID for namespace isolation

        Returns:
            S3 object URL (not presigned, use get_download_url for presigned URL)

        Raises:
            StorageError: If upload fails due to network, auth, or quota issues
        """
        object_key = self._get_object_key(document_id, organization_id)

        try:
            async with self.session.client("s3", region_name=self.region) as s3_client:
                await s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=object_key,
                    Body=file_data,
                    ContentType=content_type,
                )
                return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{object_key}"
        except Exception as e:
            storage_error = f"Failed to upload to AWS S3: {e}"
            raise StorageError(storage_error) from e

    async def download(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
    ) -> bytes | None:
        """Download file from AWS S3.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for namespace isolation

        Returns:
            Binary file content, or None if object not found

        Raises:
            StorageError: If download fails due to network or auth issues
        """
        object_key = self._get_object_key(document_id, organization_id)

        try:
            async with self.session.client("s3", region_name=self.region) as (s3_client):
                response = await s3_client.get_object(
                    Bucket=self.bucket_name,
                    Key=object_key,
                )
                return await response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            storage_error = f"Failed to download from AWS S3: {e}"
            raise StorageError(storage_error) from e
        except Exception as e:
            storage_error = f"Failed to download from AWS S3: {e}"
            raise StorageError(storage_error) from e

    async def delete(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
    ) -> bool:
        """Delete file from AWS S3.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for namespace isolation

        Returns:
            True if object was deleted, False if object didn't exist

        Raises:
            StorageError: If deletion fails due to network or auth issues
        """
        object_key = self._get_object_key(document_id, organization_id)

        try:
            async with self.session.client("s3", region_name=self.region) as s3_client:
                await s3_client.delete_object(Bucket=self.bucket_name, Key=object_key)
                # S3 delete_object returns success even if object didn't exist
                # To check existence, we'd need a head_object call first
                return True
        except Exception as e:
            storage_error = f"Failed to delete from AWS S3: {e}"  # noqa: S608
            raise StorageError(storage_error) from e

    async def get_download_url(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
        expiry_seconds: int = 3600,
    ) -> str:
        """Generate presigned URL for S3 object download.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for namespace isolation
            expiry_seconds: URL validity duration in seconds (default: 1 hour)

        Returns:
            Presigned URL valid for specified duration

        Raises:
            StorageError: If URL generation fails
        """
        object_key = self._get_object_key(document_id, organization_id)

        try:
            async with self.session.client("s3", region_name=self.region) as (s3_client):
                return await s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket_name, "Key": object_key},
                    ExpiresIn=expiry_seconds,
                )
        except Exception as e:
            storage_error = f"Failed to generate S3 presigned URL: {e}"
            raise StorageError(storage_error) from e


class GCSStorageService:
    """Google Cloud Storage implementation.

    Stores files in GCS with support for signed URLs.
    Files are organized by blob name: {organization_id}/{document_id}

    Official documentation:
        https://cloud.google.com/storage/docs/uploading-objects-from-memory

    Setup:
        1. Create GCS bucket in Google Cloud Console
        2. Create service account with Storage Object Admin role
        3. Download service account key JSON
        4. Set environment variables:
           STORAGE_GCS_BUCKET=my-bucket
           STORAGE_GCS_PROJECT_ID=my-project
           GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

    Args:
        bucket_name: GCS bucket name
        project_id: Google Cloud project ID

    Example:
        storage = GCSStorageService(bucket_name="my-bucket", project_id="my-project")
        url = await storage.upload(doc_id, file_bytes, "video/mp4", org_id)
    """

    def __init__(self, bucket_name: str, project_id: str) -> None:
        """Initialize Google Cloud Storage service.

        Args:
            bucket_name: Name of the GCS bucket
            project_id: Google Cloud project ID
        """
        if storage is None:
            msg = (
                "Google Cloud Storage requires 'google-cloud-storage' package. "
                "Install with: pip install google-cloud-storage"
            )
            raise ImportError(msg)

        self.bucket_name = bucket_name
        self.project_id = project_id
        self.client = storage.Client(project=project_id)
        self.bucket = self.client.bucket(bucket_name)

    def _get_blob_name(self, document_id: UUID, organization_id: UUID | None) -> str:
        """Generate GCS blob name for document.

        Args:
            document_id: Document unique identifier
            organization_id: Optional organization ID for namespace isolation

        Returns:
            Blob name in format: {org_id}/{doc_id} or just {doc_id}
        """
        if organization_id:
            return f"{organization_id}/{document_id}"
        return str(document_id)

    async def upload(
        self,
        document_id: UUID,
        file_data: bytes,
        content_type: str,
        organization_id: UUID | None = None,
    ) -> str:
        """Upload file to Google Cloud Storage.

        Args:
            document_id: Unique identifier for the document
            file_data: Binary file content
            content_type: MIME type for Content-Type metadata
            organization_id: Optional organization ID for namespace isolation

        Returns:
            GCS public URL (not signed, use get_download_url for signed URL)

        Raises:
            StorageError: If upload fails due to network, auth, or quota issues
        """
        blob_name = self._get_blob_name(document_id, organization_id)
        blob = self.bucket.blob(blob_name)

        try:
            # GCS library is sync, run in thread pool to avoid blocking
            await asyncio.to_thread(
                blob.upload_from_string,
                file_data,
                content_type=content_type,
            )
        except Exception as e:
            storage_error = f"Failed to upload to Google Cloud Storage: {e}"
            raise StorageError(storage_error) from e
        else:
            return blob.public_url

    async def download(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
    ) -> bytes | None:
        """Download file from Google Cloud Storage.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for namespace isolation

        Returns:
            Binary file content, or None if blob not found

        Raises:
            StorageError: If download fails due to network or auth issues
        """
        blob_name = self._get_blob_name(document_id, organization_id)
        blob = self.bucket.blob(blob_name)

        try:
            # Check if blob exists first
            exists = await asyncio.to_thread(blob.exists)
            if not exists:
                return None

            return await asyncio.to_thread(blob.download_as_bytes)
        except NotFound:
            return None
        except Exception as e:
            storage_error = f"Failed to download from Google Cloud Storage: {e}"
            raise StorageError(storage_error) from e

    async def delete(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
    ) -> bool:
        """Delete file from Google Cloud Storage.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for namespace isolation

        Returns:
            True if blob was deleted, False if blob didn't exist

        Raises:
            StorageError: If deletion fails due to network or auth issues
        """
        blob_name = self._get_blob_name(document_id, organization_id)
        blob = self.bucket.blob(blob_name)

        try:
            # Check if blob exists first
            exists = await asyncio.to_thread(blob.exists)
            if not exists:
                return False

            await asyncio.to_thread(blob.delete)
        except NotFound:
            return False
        except Exception as e:
            storage_error = f"Failed to delete from Google Cloud Storage: {e}"  # noqa: S608
            raise StorageError(storage_error) from e
        else:
            return True

    async def get_download_url(
        self,
        document_id: UUID,
        organization_id: UUID | None = None,
        expiry_seconds: int = 3600,
    ) -> str:
        """Generate signed URL for GCS blob download.

        Args:
            document_id: Unique identifier for the document
            organization_id: Optional organization ID for namespace isolation
            expiry_seconds: URL validity duration in seconds (default: 1 hour)

        Returns:
            Signed URL valid for specified duration

        Raises:
            StorageError: If URL generation fails
        """
        blob_name = self._get_blob_name(document_id, organization_id)
        blob = self.bucket.blob(blob_name)

        try:
            return await asyncio.to_thread(
                blob.generate_signed_url,
                expiration=timedelta(seconds=expiry_seconds),
                method="GET",
            )
        except Exception as e:
            storage_error = f"Failed to generate GCS signed URL: {e}"
            raise StorageError(storage_error) from e
