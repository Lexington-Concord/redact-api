"""Tests for the async MinIO-compatible StorageClient.

Uses `unittest.mock.AsyncMock` to fake the aioboto3 S3 client -- the same
async-context-manager mocking idiom as `mock_http_client_factory` in
`redact_api/tests/conftest.py`. No moto, no live MinIO.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from redact_api.storage.client import StorageClient

BUCKET = "test-bucket"


def _mock_s3_client() -> AsyncMock:
    """AsyncMock standing in for aioboto3.Session().client("s3", ...)."""
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


def _mock_session(mock_client: AsyncMock) -> MagicMock:
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    return mock_session


@pytest.fixture
def mock_s3_client() -> AsyncMock:
    return _mock_s3_client()


@pytest.fixture
def storage_client(mock_s3_client: AsyncMock) -> StorageClient:
    with patch("redact_api.storage.client.aioboto3.Session", return_value=_mock_session(mock_s3_client)):
        return StorageClient(
            endpoint="localhost:9000",
            access_key="test-access",
            secret_key="test-secret",
            bucket=BUCKET,
            secure=False,
        )


class TestStorageClientConstruction:
    def test_bucket_property(self, storage_client: StorageClient) -> None:
        assert storage_client.bucket == BUCKET

    def test_secure_flag_selects_https(self) -> None:
        with patch("redact_api.storage.client.aioboto3.Session", return_value=_mock_session(_mock_s3_client())):
            client = StorageClient(
                endpoint="minio.example.com",
                access_key="a",
                secret_key="b",
                bucket="secure-bucket",
                secure=True,
            )
        assert client._endpoint_url == "https://minio.example.com"

    def test_insecure_flag_selects_http(self) -> None:
        with patch("redact_api.storage.client.aioboto3.Session", return_value=_mock_session(_mock_s3_client())):
            client = StorageClient(
                endpoint="minio.example.com",
                access_key="a",
                secret_key="b",
                bucket="insecure-bucket",
                secure=False,
            )
        assert client._endpoint_url == "http://minio.example.com"


class TestEnsureBucket:
    @pytest.mark.anyio
    async def test_bucket_exists_no_create(self, storage_client: StorageClient, mock_s3_client: AsyncMock) -> None:
        mock_s3_client.head_bucket = AsyncMock(return_value={})
        mock_s3_client.create_bucket = AsyncMock()

        await storage_client.ensure_bucket()

        mock_s3_client.head_bucket.assert_awaited_once_with(Bucket=BUCKET)
        mock_s3_client.create_bucket.assert_not_awaited()

    @pytest.mark.anyio
    async def test_bucket_missing_creates_it(self, storage_client: StorageClient, mock_s3_client: AsyncMock) -> None:
        mock_s3_client.head_bucket = AsyncMock(side_effect=ClientError({"Error": {"Code": "404"}}, "HeadBucket"))
        mock_s3_client.create_bucket = AsyncMock(return_value={})

        await storage_client.ensure_bucket()

        mock_s3_client.create_bucket.assert_awaited_once_with(Bucket=BUCKET)

    @pytest.mark.anyio
    async def test_no_such_bucket_code_also_creates_it(
        self, storage_client: StorageClient, mock_s3_client: AsyncMock
    ) -> None:
        mock_s3_client.head_bucket = AsyncMock(
            side_effect=ClientError({"Error": {"Code": "NoSuchBucket"}}, "HeadBucket")
        )
        mock_s3_client.create_bucket = AsyncMock(return_value={})

        await storage_client.ensure_bucket()

        mock_s3_client.create_bucket.assert_awaited_once_with(Bucket=BUCKET)

    @pytest.mark.anyio
    async def test_other_client_error_reraised(self, storage_client: StorageClient, mock_s3_client: AsyncMock) -> None:
        mock_s3_client.head_bucket = AsyncMock(side_effect=ClientError({"Error": {"Code": "403"}}, "HeadBucket"))

        with pytest.raises(ClientError):
            await storage_client.ensure_bucket()


class TestUploadFile:
    @pytest.mark.anyio
    async def test_uploads_and_returns_key(
        self, storage_client: StorageClient, mock_s3_client: AsyncMock, tmp_path: Path
    ) -> None:
        local_file = tmp_path / "test.png"
        local_file.write_bytes(b"fake-png-bytes")
        mock_s3_client.upload_file = AsyncMock()

        result = await storage_client.upload_file("documents/doc-1/page-1.png", local_file)

        assert result == "documents/doc-1/page-1.png"
        mock_s3_client.upload_file.assert_awaited_once_with(str(local_file), BUCKET, "documents/doc-1/page-1.png")


class TestUploadBytes:
    @pytest.mark.anyio
    async def test_uploads_and_returns_key(self, storage_client: StorageClient, mock_s3_client: AsyncMock) -> None:
        mock_s3_client.put_object = AsyncMock()
        payload = b'{"text": "hi"}'

        result = await storage_client.upload_bytes("documents/doc-1/page-1.json", payload)

        assert result == "documents/doc-1/page-1.json"
        mock_s3_client.put_object.assert_awaited_once_with(
            Bucket=BUCKET, Key="documents/doc-1/page-1.json", Body=payload
        )


class TestDownloadFile:
    @pytest.mark.anyio
    async def test_downloads_and_creates_parent_dirs(
        self, storage_client: StorageClient, mock_s3_client: AsyncMock, tmp_path: Path
    ) -> None:
        target = tmp_path / "nested" / "dir" / "out.png"
        mock_s3_client.download_file = AsyncMock()

        result = await storage_client.download_file("documents/doc-1/page-1.png", target)

        assert result == target
        assert target.parent.exists()
        mock_s3_client.download_file.assert_awaited_once_with(BUCKET, "documents/doc-1/page-1.png", str(target))


class TestDownloadBytes:
    @pytest.mark.anyio
    async def test_downloads_and_returns_bytes(
        self, storage_client: StorageClient, mock_s3_client: AsyncMock
    ) -> None:
        mock_body = AsyncMock()
        mock_body.read = AsyncMock(return_value=b"downloaded-bytes")
        mock_s3_client.get_object = AsyncMock(return_value={"Body": mock_body})

        result = await storage_client.download_bytes("documents/doc-1/page-1.json")

        assert result == b"downloaded-bytes"
        mock_s3_client.get_object.assert_awaited_once_with(Bucket=BUCKET, Key="documents/doc-1/page-1.json")
