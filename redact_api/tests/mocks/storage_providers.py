"""Mock fixtures for cloud storage provider services.

Provides pytest fixtures that mock cloud storage services without requiring
live credentials or actual file uploads. Supports:

- Azure Blob Storage
- AWS S3
- Google Cloud Storage

Each storage fixture:
1. Patches the storage service with mock implementations
2. Tracks uploaded/downloaded files in memory
3. Simulates realistic error scenarios
4. Provides statistics about operations

Usage:
    def test_document_upload(mock_s3_storage, client):
        response = await client.post("/documents/upload", files={"file": file_data})
        assert response.status_code == 201
        # Mock storage tracked the upload
        assert mock_s3_storage['uploaded_files'][0]['name'] == 'document.pdf'

    def test_storage_error(mock_azure_storage):
        # Mock can simulate network/auth errors
        mock_azure_storage['should_fail'] = True
        response = await client.post("/documents/upload", files={...})
        assert response.status_code == 503
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from redact_api.core.config import Settings


@pytest.fixture
def mock_s3_storage(
    _test_settings_factory: Callable[..., Settings],
) -> Generator[dict[str, Any]]:
    """Mock AWS S3 storage provider.

    Fixtures provides:
    - uploaded_files: List of files uploaded to S3
    - downloaded_files: List of files downloaded from S3
    - deleted_files: List of files deleted from S3
    - should_fail: Flag to simulate S3 errors
    - failure_reason: Reason for failure (auth, connection, etc.)

    Usage:
        def test_upload_document(mock_s3_storage, client):
            response = await client.post("/documents", files={"file": data})
            assert response.status_code == 201
            assert len(mock_s3_storage['uploaded_files']) == 1
    """
    storage_data: dict[str, Any] = {
        "bucket_name": "test-bucket",
        "region": "us-east-1",
        "uploaded_files": [],
        "downloaded_files": [],
        "deleted_files": [],
        "should_fail": False,
        "failure_reason": None,
    }

    async def mock_upload(
        document_id: UUID,
        file_data: bytes,
        content_type: str,
        organization_id: UUID | None = None,
    ) -> str:
        msg = storage_data["failure_reason"] or "S3 error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        storage_data["uploaded_files"].append(
            {
                "document_id": str(document_id),
                "size": len(file_data),
                "content_type": content_type,
                "organization_id": str(organization_id) if organization_id else None,
            }
        )
        return f"s3://test-bucket/{document_id}"

    async def mock_download(document_id: UUID, _organization_id: UUID | None = None) -> bytes | None:
        msg = storage_data["failure_reason"] or "S3 error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        storage_data["downloaded_files"].append(str(document_id))
        return b"mock file content"

    async def mock_delete(document_id: UUID, _organization_id: UUID | None = None) -> bool:
        msg = storage_data["failure_reason"] or "S3 error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        storage_data["deleted_files"].append(str(document_id))
        return True

    async def mock_get_download_url(
        document_id: UUID,
        _organization_id: UUID | None = None,
        expiry_seconds: int = 3600,
    ) -> str:
        msg = storage_data["failure_reason"] or "S3 error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        return f"https://test-bucket.s3.amazonaws.com/{document_id}?expires={expiry_seconds}"

    mock_service = MagicMock()
    mock_service.upload = mock_upload
    mock_service.download = mock_download
    mock_service.delete = mock_delete
    mock_service.get_download_url = mock_get_download_url

    with patch("redact_api.core.storage.get_storage_service", return_value=mock_service):
        storage_data["service"] = mock_service
        yield storage_data


@pytest.fixture
def mock_azure_storage(
    _test_settings_factory: Callable[..., Settings],
) -> Generator[dict[str, Any]]:
    """Mock Azure Blob Storage provider.

    Provides:
    - uploaded_files: List of files uploaded to Azure
    - container_name: Azure container name
    - should_fail: Flag to simulate Azure errors
    - failure_reason: Reason for failure

    Usage:
        def test_blob_storage(mock_azure_storage, client):
            response = await client.post("/documents", files={"file": data})
            assert response.status_code == 201
            assert len(mock_azure_storage['uploaded_files']) == 1
    """
    storage_data: dict[str, Any] = {
        "container_name": "test-container",
        "uploaded_files": [],
        "downloaded_files": [],
        "deleted_files": [],
        "should_fail": False,
        "failure_reason": None,
    }

    async def mock_upload(
        document_id: UUID,
        file_data: bytes,
        content_type: str,
        organization_id: UUID | None = None,  # noqa: ARG001
    ) -> str:
        msg = storage_data["failure_reason"] or "Azure error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        storage_data["uploaded_files"].append(
            {
                "document_id": str(document_id),
                "size": len(file_data),
                "content_type": content_type,
            }
        )
        return f"https://teststorage.blob.core.windows.net/test-container/{document_id}"

    async def mock_download(document_id: UUID, _organization_id: UUID | None = None) -> bytes | None:
        msg = storage_data["failure_reason"] or "Azure error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        storage_data["downloaded_files"].append(str(document_id))
        return b"mock file content"

    async def mock_delete(document_id: UUID, _organization_id: UUID | None = None) -> bool:
        msg = storage_data["failure_reason"] or "Azure error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        storage_data["deleted_files"].append(str(document_id))
        return True

    async def mock_get_download_url(
        document_id: UUID,
        _organization_id: UUID | None = None,
        _expiry_seconds: int = 3600,
    ) -> str:
        msg = storage_data["failure_reason"] or "Azure error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        return f"https://teststorage.blob.core.windows.net/test-container/{document_id}?sv=test"

    mock_service = MagicMock()
    mock_service.upload = mock_upload
    mock_service.download = mock_download
    mock_service.delete = mock_delete
    mock_service.get_download_url = mock_get_download_url

    with patch("redact_api.core.storage.get_storage_service", return_value=mock_service):
        storage_data["service"] = mock_service
        yield storage_data


@pytest.fixture
def mock_gcs_storage(
    _test_settings_factory: Callable[..., Settings],
) -> Generator[dict[str, Any]]:
    """Mock Google Cloud Storage provider.

    Provides:
    - uploaded_files: List of files uploaded to GCS
    - bucket_name: GCS bucket name
    - project_id: GCP project ID
    - should_fail: Flag to simulate GCS errors

    Usage:
        def test_gcs_upload(mock_gcs_storage, client):
            response = await client.post("/documents", files={"file": data})
            assert response.status_code == 201
            assert len(mock_gcs_storage['uploaded_files']) == 1
    """
    storage_data: dict[str, Any] = {
        "bucket_name": "test-bucket",
        "project_id": "test-project",
        "uploaded_files": [],
        "downloaded_files": [],
        "deleted_files": [],
        "should_fail": False,
        "failure_reason": None,
    }

    async def mock_upload(
        document_id: UUID,
        file_data: bytes,
        content_type: str,
        organization_id: UUID | None = None,  # noqa: ARG001
    ) -> str:
        msg = storage_data["failure_reason"] or "GCS error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        storage_data["uploaded_files"].append(
            {
                "document_id": str(document_id),
                "size": len(file_data),
                "content_type": content_type,
            }
        )
        return f"gs://test-bucket/{document_id}"

    async def mock_download(document_id: UUID, _organization_id: UUID | None = None) -> bytes | None:
        msg = storage_data["failure_reason"] or "GCS error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        storage_data["downloaded_files"].append(str(document_id))
        return b"mock file content"

    async def mock_delete(document_id: UUID, _organization_id: UUID | None = None) -> bool:
        msg = storage_data["failure_reason"] or "GCS error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        storage_data["deleted_files"].append(str(document_id))
        return True

    async def mock_get_download_url(
        document_id: UUID,
        _organization_id: UUID | None = None,
        expiry_seconds: int = 3600,
    ) -> str:
        msg = storage_data["failure_reason"] or "GCS error"
        if storage_data["should_fail"]:
            raise RuntimeError(msg)
        return f"https://storage.googleapis.com/test-bucket/{document_id}?expires={expiry_seconds}"

    mock_service = MagicMock()
    mock_service.upload = mock_upload
    mock_service.download = mock_download
    mock_service.delete = mock_delete
    mock_service.get_download_url = mock_get_download_url

    with patch("redact_api.core.storage.get_storage_service", return_value=mock_service):
        storage_data["service"] = mock_service
        yield storage_data
