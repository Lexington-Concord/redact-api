"""Comprehensive tests for storage provider implementations.

Tests the actual storage operations (upload, download, delete, get_download_url)
for all storage providers using mocks for cloud SDKs.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from redact_api.core.storage import StorageError
from redact_api.core.storage_providers import (
    AzureBlobStorageService,
    GCSStorageService,
    LocalStorageService,
    S3StorageService,
    _is_transient_storage_error,
    _log_storage_retry,
    create_storage_retry,
)

if TYPE_CHECKING:
    from collections.abc import Generator


# Test UUIDs
TEST_DOC_ID = UUID("12345678-1234-5678-1234-567812345678")
TEST_ORG_ID = UUID("87654321-4321-8765-4321-876543218765")


class TestLocalStorageService:
    """Tests for LocalStorageService."""

    @pytest.fixture
    def temp_storage_path(self, tmp_path: Path) -> Path:
        """Create a temporary storage directory."""
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()
        return storage_dir

    @pytest.fixture
    def storage(self, temp_storage_path: Path) -> LocalStorageService:
        """Create a LocalStorageService instance."""
        return LocalStorageService(str(temp_storage_path))

    @pytest.mark.asyncio
    async def test_upload_creates_file(self, storage: LocalStorageService) -> None:
        """Upload should create file at correct path."""
        content = b"test file content"
        url = await storage.upload(TEST_DOC_ID, content, "text/plain")

        assert Path(url).exists()
        assert Path(url).read_bytes() == content

    @pytest.mark.asyncio
    async def test_upload_with_organization(self, storage: LocalStorageService) -> None:
        """Upload with org_id should create file in org subdirectory."""
        content = b"org specific content"
        url = await storage.upload(TEST_DOC_ID, content, "text/plain", TEST_ORG_ID)

        assert Path(url).exists()
        assert str(TEST_ORG_ID) in url
        assert Path(url).read_bytes() == content

    @pytest.mark.asyncio
    async def test_upload_permission_error(self, tmp_path: Path) -> None:
        """Upload should raise StorageError on permission failure."""
        # Create a read-only directory
        read_only_dir = tmp_path / "readonly"
        read_only_dir.mkdir()
        read_only_dir.chmod(0o444)

        try:
            storage = LocalStorageService(str(read_only_dir))
            with pytest.raises(StorageError, match="Failed to write"):
                await storage.upload(TEST_DOC_ID, b"content", "text/plain")
        finally:
            read_only_dir.chmod(0o755)

    @pytest.mark.asyncio
    async def test_download_existing_file(self, storage: LocalStorageService) -> None:
        """Download should return file content."""
        content = b"download test content"
        await storage.upload(TEST_DOC_ID, content, "text/plain")

        result = await storage.download(TEST_DOC_ID)
        assert result == content

    @pytest.mark.asyncio
    async def test_download_nonexistent_file(self, storage: LocalStorageService) -> None:
        """Download should return None for missing file."""
        result = await storage.download(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_download_with_organization(self, storage: LocalStorageService) -> None:
        """Download with org_id should find file in org subdirectory."""
        content = b"org download content"
        await storage.upload(TEST_DOC_ID, content, "text/plain", TEST_ORG_ID)

        result = await storage.download(TEST_DOC_ID, TEST_ORG_ID)
        assert result == content

    @pytest.mark.asyncio
    async def test_delete_existing_file(self, storage: LocalStorageService) -> None:
        """Delete should remove file and return True."""
        await storage.upload(TEST_DOC_ID, b"to delete", "text/plain")

        result = await storage.delete(TEST_DOC_ID)
        assert result is True
        assert await storage.download(TEST_DOC_ID) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self, storage: LocalStorageService) -> None:
        """Delete should return False for missing file."""
        result = await storage.delete(uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_with_organization(self, storage: LocalStorageService) -> None:
        """Delete with org_id should remove file from org subdirectory."""
        await storage.upload(TEST_DOC_ID, b"org delete", "text/plain", TEST_ORG_ID)

        result = await storage.delete(TEST_DOC_ID, TEST_ORG_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_download_url(self, storage: LocalStorageService) -> None:
        """Get download URL should return file path."""
        await storage.upload(TEST_DOC_ID, b"content", "text/plain")

        url = await storage.get_download_url(TEST_DOC_ID)
        assert str(TEST_DOC_ID) in url

    @pytest.mark.asyncio
    async def test_get_download_url_with_organization(self, storage: LocalStorageService) -> None:
        """Get download URL with org_id should include org in path."""
        await storage.upload(TEST_DOC_ID, b"content", "text/plain", TEST_ORG_ID)

        url = await storage.get_download_url(TEST_DOC_ID, TEST_ORG_ID)
        assert str(TEST_ORG_ID) in url
        assert str(TEST_DOC_ID) in url

    def test_init_creates_directory(self, tmp_path: Path) -> None:
        """Init should create base directory if it doesn't exist."""
        new_path = tmp_path / "new_storage"
        assert not new_path.exists()

        LocalStorageService(str(new_path))
        assert new_path.exists()

    def test_init_handles_permission_error(self) -> None:
        """Init should not fail if directory creation fails."""
        # This tests the contextlib.suppress behavior
        with patch.object(Path, "mkdir", side_effect=PermissionError("denied")):
            # Should not raise, just suppress the error
            storage = LocalStorageService("/nonexistent/path")
            assert storage.base_path == Path("/nonexistent/path")


class TestAzureBlobStorageServiceMocked:
    """Tests for AzureBlobStorageService using mocks."""

    @pytest.fixture
    def mock_azure_modules(self) -> Generator[dict[str, Any]]:
        """Mock Azure SDK modules."""
        mock_blob_client = MagicMock()
        mock_blob_client.url = "https://account.blob.core.windows.net/container/blob"
        mock_blob_client.upload_blob = AsyncMock()
        mock_blob_client.download_blob = AsyncMock()
        mock_blob_client.delete_blob = AsyncMock()

        mock_download_stream = AsyncMock()
        mock_download_stream.readall = AsyncMock(return_value=b"downloaded content")
        mock_blob_client.download_blob.return_value = mock_download_stream

        mock_service_client = MagicMock()
        mock_service_client.get_blob_client.return_value = mock_blob_client

        mock_blob_service_class = MagicMock()
        mock_blob_service_class.from_connection_string.return_value = mock_service_client

        mock_sas_permissions = MagicMock()
        mock_generate_sas = MagicMock(return_value="sas_token_123")

        # Create mock exception
        class MockResourceNotFoundError(Exception):
            pass

        mocks = {
            "BlobServiceClient": mock_blob_service_class,
            "blob_client": mock_blob_client,
            "service_client": mock_service_client,
            "BlobSasPermissions": mock_sas_permissions,
            "generate_blob_sas": mock_generate_sas,
            "AzureResourceNotFoundError": MockResourceNotFoundError,
        }

        with (
            patch(
                "redact_api.core.storage_providers.BlobServiceClient",
                mock_blob_service_class,
            ),
            patch(
                "redact_api.core.storage_providers.BlobSasPermissions",
                mock_sas_permissions,
            ),
            patch(
                "redact_api.core.storage_providers.generate_blob_sas",
                mock_generate_sas,
            ),
            patch(
                "redact_api.core.storage_providers.AzureResourceNotFoundError",
                MockResourceNotFoundError,
            ),
        ):
            yield mocks

    @pytest.mark.asyncio
    async def test_upload_success(self, mock_azure_modules: dict[str, Any]) -> None:
        """Azure upload should call blob client correctly."""
        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=test;AccountKey=key",
        )

        url = await storage.upload(TEST_DOC_ID, b"content", "text/plain", TEST_ORG_ID)

        assert url == mock_azure_modules["blob_client"].url
        mock_azure_modules["blob_client"].upload_blob.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_error(self, mock_azure_modules: dict[str, Any]) -> None:
        """Azure upload should wrap errors in StorageError."""
        mock_azure_modules["blob_client"].upload_blob.side_effect = Exception("Upload failed")

        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=test;AccountKey=key",
        )

        with pytest.raises(StorageError, match="Failed to upload"):
            await storage.upload(TEST_DOC_ID, b"content", "text/plain")

    @pytest.mark.asyncio
    async def test_download_success(self, mock_azure_modules: dict[str, Any]) -> None:
        """Azure download should return blob content."""
        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=test;AccountKey=key",
        )

        result = await storage.download(TEST_DOC_ID)
        assert result == b"downloaded content"

    @pytest.mark.asyncio
    async def test_download_not_found(self, mock_azure_modules: dict[str, Any]) -> None:
        """Azure download should return None for missing blob."""
        mock_azure_modules["blob_client"].download_blob.side_effect = mock_azure_modules["AzureResourceNotFoundError"](
            "Not found"
        )

        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=test;AccountKey=key",
        )

        result = await storage.download(TEST_DOC_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_download_error(self, mock_azure_modules: dict[str, Any]) -> None:
        """Azure download should wrap errors in StorageError."""
        mock_azure_modules["blob_client"].download_blob.side_effect = Exception("Download failed")

        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=test;AccountKey=key",
        )

        with pytest.raises(StorageError, match="Failed to download"):
            await storage.download(TEST_DOC_ID)

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_azure_modules: dict[str, Any]) -> None:
        """Azure delete should return True on success."""
        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=test;AccountKey=key",
        )

        result = await storage.delete(TEST_DOC_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self, mock_azure_modules: dict[str, Any]) -> None:
        """Azure delete should return False for missing blob."""
        mock_azure_modules["blob_client"].delete_blob.side_effect = mock_azure_modules["AzureResourceNotFoundError"](
            "Not found"
        )

        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=test;AccountKey=key",
        )

        result = await storage.delete(TEST_DOC_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_error(self, mock_azure_modules: dict[str, Any]) -> None:
        """Azure delete should wrap errors in StorageError."""
        mock_azure_modules["blob_client"].delete_blob.side_effect = Exception("Delete failed")

        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=test;AccountKey=key",
        )

        with pytest.raises(StorageError, match="Failed to delete"):
            await storage.delete(TEST_DOC_ID)

    @pytest.mark.asyncio
    async def test_get_download_url_success(self, mock_azure_modules: dict[str, Any]) -> None:
        """Azure get_download_url should return signed URL."""
        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=testaccount;AccountKey=testkey",
        )

        url = await storage.get_download_url(TEST_DOC_ID, expiry_seconds=7200)

        assert "sas_token_123" in url
        mock_azure_modules["generate_blob_sas"].assert_called_once()

    @pytest.mark.asyncio
    async def test_get_download_url_error(self, mock_azure_modules: dict[str, Any]) -> None:
        """Azure get_download_url should wrap errors in StorageError."""
        mock_azure_modules["generate_blob_sas"].side_effect = Exception("SAS failed")

        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=test;AccountKey=key",
        )

        with pytest.raises(StorageError, match="Failed to generate"):
            await storage.get_download_url(TEST_DOC_ID)

    def test_get_blob_name_with_org(self, mock_azure_modules: dict[str, Any]) -> None:
        """Blob name should include org ID when provided."""
        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=test;AccountKey=key",
        )

        blob_name = storage._get_blob_name(TEST_DOC_ID, TEST_ORG_ID)
        assert str(TEST_ORG_ID) in blob_name
        assert str(TEST_DOC_ID) in blob_name

    def test_get_blob_name_without_org(self, mock_azure_modules: dict[str, Any]) -> None:
        """Blob name should be just doc ID when no org provided."""
        storage = AzureBlobStorageService(
            container_name="test-container",
            connection_string="AccountName=test;AccountKey=key",
        )

        blob_name = storage._get_blob_name(TEST_DOC_ID, None)
        assert blob_name == str(TEST_DOC_ID)

    def test_init_without_azure_sdk(self) -> None:
        """Should raise ImportError when Azure SDK is missing."""
        with (
            patch(
                "redact_api.core.storage_providers.BlobServiceClient",
                None,
            ),
            pytest.raises(ImportError, match="azure-storage-blob"),
        ):
            AzureBlobStorageService(
                container_name="test",
                connection_string="conn",
            )


class TestS3StorageServiceMocked:
    """Tests for S3StorageService using mocks."""

    @pytest.fixture
    def mock_s3_modules(self) -> Generator[dict[str, Any]]:
        """Mock AWS S3 SDK modules."""
        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock()
        mock_s3_client.get_object = AsyncMock()
        mock_s3_client.delete_object = AsyncMock()
        mock_s3_client.generate_presigned_url = AsyncMock(return_value="https://s3.presigned.url")

        mock_body = AsyncMock()
        mock_body.read = AsyncMock(return_value=b"s3 content")
        mock_s3_client.get_object.return_value = {"Body": mock_body}

        mock_session = MagicMock()
        mock_context_manager = MagicMock()
        mock_context_manager.__aenter__ = AsyncMock(return_value=mock_s3_client)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)
        mock_session.client.return_value = mock_context_manager

        # Create mock ClientError
        class MockClientError(Exception):
            def __init__(self, error_response: dict[str, Any], operation_name: str) -> None:
                self.response = error_response
                self.operation_name = operation_name
                super().__init__(f"{operation_name}: {error_response}")

        mocks = {
            "session": mock_session,
            "s3_client": mock_s3_client,
            "ClientError": MockClientError,
        }

        # Mock aioboto3 module
        mock_aioboto3 = MagicMock()
        mock_aioboto3.Session.return_value = mock_session

        with (
            patch("redact_api.core.storage_providers.aioboto3", mock_aioboto3),
            patch(
                "redact_api.core.storage_providers.ClientError",
                MockClientError,
            ),
        ):
            yield mocks

    @pytest.mark.asyncio
    async def test_upload_success(self, mock_s3_modules: dict[str, Any]) -> None:
        """S3 upload should call put_object correctly."""
        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        url = await storage.upload(TEST_DOC_ID, b"content", "text/plain", TEST_ORG_ID)

        assert "test-bucket" in url
        assert "us-east-1" in url
        mock_s3_modules["s3_client"].put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_error(self, mock_s3_modules: dict[str, Any]) -> None:
        """S3 upload should wrap errors in StorageError."""
        mock_s3_modules["s3_client"].put_object.side_effect = Exception("Upload failed")

        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        with pytest.raises(StorageError, match="Failed to upload"):
            await storage.upload(TEST_DOC_ID, b"content", "text/plain")

    @pytest.mark.asyncio
    async def test_download_success(self, mock_s3_modules: dict[str, Any]) -> None:
        """S3 download should return object content."""
        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        result = await storage.download(TEST_DOC_ID)
        assert result == b"s3 content"

    @pytest.mark.asyncio
    async def test_download_not_found(self, mock_s3_modules: dict[str, Any]) -> None:
        """S3 download should return None for missing object."""
        mock_s3_modules["s3_client"].get_object.side_effect = mock_s3_modules["ClientError"](
            {"Error": {"Code": "NoSuchKey"}}, "GetObject"
        )

        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        result = await storage.download(TEST_DOC_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_download_client_error(self, mock_s3_modules: dict[str, Any]) -> None:
        """S3 download should wrap client errors in StorageError."""
        mock_s3_modules["s3_client"].get_object.side_effect = mock_s3_modules["ClientError"](
            {"Error": {"Code": "AccessDenied"}}, "GetObject"
        )

        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        with pytest.raises(StorageError, match="Failed to download"):
            await storage.download(TEST_DOC_ID)

    @pytest.mark.asyncio
    async def test_download_generic_error(self, mock_s3_modules: dict[str, Any]) -> None:
        """S3 download should wrap generic errors in StorageError."""
        mock_s3_modules["s3_client"].get_object.side_effect = Exception("Network error")

        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        with pytest.raises(StorageError, match="Failed to download"):
            await storage.download(TEST_DOC_ID)

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_s3_modules: dict[str, Any]) -> None:
        """S3 delete should return True on success."""
        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        result = await storage.delete(TEST_DOC_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_error(self, mock_s3_modules: dict[str, Any]) -> None:
        """S3 delete should wrap errors in StorageError."""
        mock_s3_modules["s3_client"].delete_object.side_effect = Exception("Delete failed")

        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        with pytest.raises(StorageError, match="Failed to delete"):
            await storage.delete(TEST_DOC_ID)

    @pytest.mark.asyncio
    async def test_get_download_url_success(self, mock_s3_modules: dict[str, Any]) -> None:
        """S3 get_download_url should return presigned URL."""
        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        url = await storage.get_download_url(TEST_DOC_ID, expiry_seconds=7200)

        assert url == "https://s3.presigned.url"
        mock_s3_modules["s3_client"].generate_presigned_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_download_url_error(self, mock_s3_modules: dict[str, Any]) -> None:
        """S3 get_download_url should wrap errors in StorageError."""
        mock_s3_modules["s3_client"].generate_presigned_url.side_effect = Exception("URL generation failed")

        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        with pytest.raises(StorageError, match="Failed to generate"):
            await storage.get_download_url(TEST_DOC_ID)

    def test_get_object_key_with_org(self, mock_s3_modules: dict[str, Any]) -> None:
        """Object key should include org ID when provided."""
        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        key = storage._get_object_key(TEST_DOC_ID, TEST_ORG_ID)
        assert str(TEST_ORG_ID) in key
        assert str(TEST_DOC_ID) in key

    def test_get_object_key_without_org(self, mock_s3_modules: dict[str, Any]) -> None:
        """Object key should be just doc ID when no org provided."""
        storage = S3StorageService(bucket_name="test-bucket", region="us-east-1")

        key = storage._get_object_key(TEST_DOC_ID, None)
        assert key == str(TEST_DOC_ID)

    def test_init_without_aioboto3(self) -> None:
        """Should raise ImportError when aioboto3 is missing."""
        with (
            patch("redact_api.core.storage_providers.aioboto3", None),
            pytest.raises(ImportError, match="aioboto3"),
        ):
            S3StorageService(bucket_name="test", region="us-east-1")


class TestGCSStorageServiceMocked:
    """Tests for GCSStorageService using mocks."""

    @pytest.fixture
    def mock_gcs_modules(self) -> Generator[dict[str, Any]]:
        """Mock Google Cloud Storage SDK modules."""
        mock_blob = MagicMock()
        mock_blob.public_url = "https://storage.googleapis.com/bucket/blob"
        mock_blob.upload_from_string = MagicMock()
        mock_blob.download_as_bytes = MagicMock(return_value=b"gcs content")
        mock_blob.exists = MagicMock(return_value=True)
        mock_blob.delete = MagicMock()
        mock_blob.generate_signed_url = MagicMock(return_value="https://storage.googleapis.com/signed")

        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob

        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        # Create mock NotFound exception
        class MockNotFoundError(Exception):
            pass

        mock_storage = MagicMock()
        mock_storage.Client.return_value = mock_client

        mocks = {
            "client": mock_client,
            "bucket": mock_bucket,
            "blob": mock_blob,
            "storage": mock_storage,
            "NotFound": MockNotFoundError,
        }

        with (
            patch("redact_api.core.storage_providers.storage", mock_storage),
            patch("redact_api.core.storage_providers.NotFound", MockNotFoundError),
        ):
            yield mocks

    @pytest.mark.asyncio
    async def test_upload_success(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS upload should call upload_from_string correctly."""
        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        url = await storage.upload(TEST_DOC_ID, b"content", "text/plain", TEST_ORG_ID)

        assert url == mock_gcs_modules["blob"].public_url

    @pytest.mark.asyncio
    async def test_upload_error(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS upload should wrap errors in StorageError."""
        mock_gcs_modules["blob"].upload_from_string.side_effect = Exception("Upload failed")

        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        with pytest.raises(StorageError, match="Failed to upload"):
            await storage.upload(TEST_DOC_ID, b"content", "text/plain")

    @pytest.mark.asyncio
    async def test_download_success(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS download should return blob content."""
        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        result = await storage.download(TEST_DOC_ID)
        assert result == b"gcs content"

    @pytest.mark.asyncio
    async def test_download_not_exists(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS download should return None when blob doesn't exist."""
        mock_gcs_modules["blob"].exists.return_value = False

        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        result = await storage.download(TEST_DOC_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_download_not_found_exception(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS download should return None on NotFound exception."""
        mock_gcs_modules["blob"].download_as_bytes.side_effect = mock_gcs_modules["NotFound"]("Not found")

        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        result = await storage.download(TEST_DOC_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_download_error(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS download should wrap errors in StorageError."""
        mock_gcs_modules["blob"].download_as_bytes.side_effect = Exception("Download failed")

        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        with pytest.raises(StorageError, match="Failed to download"):
            await storage.download(TEST_DOC_ID)

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS delete should return True on success."""
        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        result = await storage.delete(TEST_DOC_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_not_exists(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS delete should return False when blob doesn't exist."""
        mock_gcs_modules["blob"].exists.return_value = False

        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        result = await storage.delete(TEST_DOC_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_not_found_exception(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS delete should return False on NotFound exception."""
        mock_gcs_modules["blob"].delete.side_effect = mock_gcs_modules["NotFound"]("Not found")

        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        result = await storage.delete(TEST_DOC_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_error(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS delete should wrap errors in StorageError."""
        mock_gcs_modules["blob"].delete.side_effect = Exception("Delete failed")

        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        with pytest.raises(StorageError, match="Failed to delete"):
            await storage.delete(TEST_DOC_ID)

    @pytest.mark.asyncio
    async def test_get_download_url_success(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS get_download_url should return signed URL."""
        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        url = await storage.get_download_url(TEST_DOC_ID, expiry_seconds=7200)

        assert url == "https://storage.googleapis.com/signed"

    @pytest.mark.asyncio
    async def test_get_download_url_error(self, mock_gcs_modules: dict[str, Any]) -> None:
        """GCS get_download_url should wrap errors in StorageError."""
        mock_gcs_modules["blob"].generate_signed_url.side_effect = Exception("URL generation failed")

        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        with pytest.raises(StorageError, match="Failed to generate"):
            await storage.get_download_url(TEST_DOC_ID)

    def test_get_blob_name_with_org(self, mock_gcs_modules: dict[str, Any]) -> None:
        """Blob name should include org ID when provided."""
        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        blob_name = storage._get_blob_name(TEST_DOC_ID, TEST_ORG_ID)
        assert str(TEST_ORG_ID) in blob_name
        assert str(TEST_DOC_ID) in blob_name

    def test_get_blob_name_without_org(self, mock_gcs_modules: dict[str, Any]) -> None:
        """Blob name should be just doc ID when no org provided."""
        storage = GCSStorageService(bucket_name="test-bucket", project_id="test-project")

        blob_name = storage._get_blob_name(TEST_DOC_ID, None)
        assert blob_name == str(TEST_DOC_ID)

    def test_init_without_gcs_sdk(self) -> None:
        """Should raise ImportError when GCS SDK is missing."""
        with (
            patch("redact_api.core.storage_providers.storage", None),
            pytest.raises(ImportError, match="google-cloud-storage"),
        ):
            GCSStorageService(bucket_name="test", project_id="test")


class TestTransientStorageErrorDetection:
    """Tests for _is_transient_storage_error function."""

    def test_timeout_error(self) -> None:
        """Timeout errors should be transient."""
        error = Exception("Connection timeout occurred")
        assert _is_transient_storage_error(error) is True

    def test_connection_reset_error(self) -> None:
        """Connection reset errors should be transient."""
        error = Exception("Connection reset by peer")
        assert _is_transient_storage_error(error) is True

    def test_connection_refused_error(self) -> None:
        """Connection refused errors should be transient."""
        error = Exception("Connection refused")
        assert _is_transient_storage_error(error) is True

    def test_temporary_failure_error(self) -> None:
        """Temporary failure errors should be transient."""
        error = Exception("Temporary failure in name resolution")
        assert _is_transient_storage_error(error) is True

    def test_service_unavailable_error(self) -> None:
        """Service unavailable errors should be transient."""
        error = Exception("Service unavailable, try again later")
        assert _is_transient_storage_error(error) is True

    def test_too_many_requests_error(self) -> None:
        """Too many requests errors should be transient."""
        error = Exception("Too many requests")
        assert _is_transient_storage_error(error) is True

    def test_azure_service_unavailable_error(self) -> None:
        """Azure ServiceUnavailable exception type should be transient."""

        class ServiceUnavailableError(Exception):
            pass

        error = ServiceUnavailableError("Service unavailable")
        assert _is_transient_storage_error(error) is True

    def test_s3_throttling_error(self) -> None:
        """S3 Throttling errors should be transient."""

        class MockClientError(Exception):
            def __init__(self) -> None:
                self.response = {"Error": {"Code": "Throttling"}}

        with patch("redact_api.core.storage_providers.ClientError", MockClientError):
            error = MockClientError()
            assert _is_transient_storage_error(error) is True

    def test_s3_service_unavailable_error(self) -> None:
        """S3 ServiceUnavailable errors should be transient."""

        class MockClientError(Exception):
            def __init__(self) -> None:
                self.response = {"Error": {"Code": "ServiceUnavailable"}}

        with patch("redact_api.core.storage_providers.ClientError", MockClientError):
            error = MockClientError()
            assert _is_transient_storage_error(error) is True

    def test_s3_slow_down_error(self) -> None:
        """S3 SlowDown errors should be transient."""

        class MockClientError(Exception):
            def __init__(self) -> None:
                self.response = {"Error": {"Code": "SlowDown"}}

        with patch("redact_api.core.storage_providers.ClientError", MockClientError):
            error = MockClientError()
            assert _is_transient_storage_error(error) is True

    def test_s3_request_timeout_error(self) -> None:
        """S3 RequestTimeout errors should be transient."""

        class MockClientError(Exception):
            def __init__(self) -> None:
                self.response = {"Error": {"Code": "RequestTimeout"}}

        with patch("redact_api.core.storage_providers.ClientError", MockClientError):
            error = MockClientError()
            assert _is_transient_storage_error(error) is True

    def test_s3_non_transient_client_error(self) -> None:
        """S3 AccessDenied errors should NOT be transient."""

        class MockClientError(Exception):
            def __init__(self) -> None:
                self.response = {"Error": {"Code": "AccessDenied"}}

        with patch("redact_api.core.storage_providers.ClientError", MockClientError):
            error = MockClientError()
            assert _is_transient_storage_error(error) is False

    def test_permanent_error(self) -> None:
        """Permanent errors should NOT be transient."""
        error = Exception("File not found")
        assert _is_transient_storage_error(error) is False

    def test_auth_error(self) -> None:
        """Authentication errors should NOT be transient."""
        error = Exception("Invalid credentials")
        assert _is_transient_storage_error(error) is False


class TestStorageRetryLogging:
    """Tests for _log_storage_retry function."""

    def test_log_retry_with_exception(self) -> None:
        """Should log retry attempt with exception details."""
        mock_outcome = MagicMock()
        mock_outcome.exception.return_value = ValueError("Test error")

        mock_retry_state = MagicMock()
        mock_retry_state.attempt_number = 2
        mock_retry_state.outcome = mock_outcome

        with (
            patch("redact_api.core.storage_providers.LOGGER") as mock_logger,
            patch(
                "redact_api.core.storage_providers.get_logging_context",
                return_value={"request_id": "test-123"},
            ),
        ):
            _log_storage_retry(mock_retry_state)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "storage_operation_retry"
            extra = call_args[1]["extra"]
            assert extra["attempt"] == 2
            assert extra["exception_type"] == "ValueError"
            assert "Test error" in extra["exception_message"]

    def test_log_retry_without_outcome(self) -> None:
        """Should handle retry state without outcome."""
        mock_retry_state = MagicMock()
        mock_retry_state.attempt_number = 1
        mock_retry_state.outcome = None

        with (
            patch("redact_api.core.storage_providers.LOGGER") as mock_logger,
            patch(
                "redact_api.core.storage_providers.get_logging_context",
                return_value={},
            ),
        ):
            _log_storage_retry(mock_retry_state)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            extra = call_args[1]["extra"]
            assert extra["exception_type"] == "unknown"
            assert extra["exception_message"] == ""


class TestCreateStorageRetry:
    """Tests for create_storage_retry factory function."""

    def test_creates_retry_decorator(self) -> None:
        """Should create a callable retry decorator."""
        decorator = create_storage_retry()
        assert callable(decorator)

    def test_custom_parameters(self) -> None:
        """Should accept custom retry parameters."""
        decorator = create_storage_retry(max_attempts=5, min_wait=2, max_wait=30)
        assert callable(decorator)

    @pytest.mark.asyncio
    async def test_decorated_function_retries(self) -> None:
        """Decorated function should retry on failure."""
        call_count = 0

        @create_storage_retry(max_attempts=3, min_wait=0, max_wait=0)
        async def flaky_operation() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                msg = "Transient error"
                raise Exception(msg)
            return "success"

        result = await flaky_operation()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_decorated_function_exhausts_retries(self) -> None:
        """Decorated function should fail after max retries."""

        @create_storage_retry(max_attempts=2, min_wait=0, max_wait=0)
        async def always_fails() -> str:
            msg = "Permanent error"
            raise Exception(msg)

        with pytest.raises(Exception, match="Permanent error"):
            await always_fails()
