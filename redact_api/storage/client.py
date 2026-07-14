"""Async S3-compatible storage client for MinIO.

Provides upload/download operations for ingest pipeline artifacts (page
rasters, text-layer JSON). Uses aioboto3 for async S3 API compatibility.

Mirrors the shape of services/minutes-shared/minutes_shared/storage/client.py
(same constructor signature and method set) but is a standalone
implementation -- this service does not import minutes_shared.

Usage:
    client = StorageClient(
        endpoint="localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket="redact-pipeline",
    )
    await client.ensure_bucket()
    await client.upload_bytes("documents/123/pages/1/raster.png", png_bytes)
    data = await client.download_bytes("documents/123/pages/1/raster.png")
"""

from __future__ import annotations

import logging
from pathlib import Path

import aioboto3
from botocore.exceptions import ClientError

LOGGER = logging.getLogger(__name__)


class StorageClient:
    """Async S3-compatible client for MinIO object storage."""

    def __init__(
        self,
        *,
        endpoint: str = "localhost:9000",
        access_key: str,
        secret_key: str,
        bucket: str = "redact-pipeline",
        secure: bool = False,
    ) -> None:
        protocol = "https" if secure else "http"
        self._endpoint_url = f"{protocol}://{endpoint}"
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._session = aioboto3.Session()

    async def ensure_bucket(self) -> None:
        """Create the pipeline bucket if it doesn't exist."""
        async with self._session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        ) as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code in ("404", "NoSuchBucket"):
                    LOGGER.info("creating_bucket", extra={"bucket": self._bucket})
                    await s3.create_bucket(Bucket=self._bucket)
                else:
                    raise

    async def upload_file(self, object_key: str, file_path: Path) -> str:
        """Upload a local file to MinIO.

        Args:
            object_key: S3 object key (e.g., "documents/123/pages/1/raster.png")
            file_path: Local file path to upload

        Returns:
            The object key that was uploaded
        """
        async with self._session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        ) as s3:
            await s3.upload_file(str(file_path), self._bucket, object_key)
            LOGGER.info(
                "file_uploaded",
                extra={"bucket": self._bucket, "key": object_key, "size_bytes": file_path.stat().st_size},
            )
        return object_key

    async def upload_bytes(self, object_key: str, data: bytes) -> str:
        """Upload raw bytes to MinIO.

        Args:
            object_key: S3 object key
            data: Bytes to upload

        Returns:
            The object key that was uploaded
        """
        async with self._session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        ) as s3:
            await s3.put_object(Bucket=self._bucket, Key=object_key, Body=data)
            LOGGER.info(
                "bytes_uploaded",
                extra={"bucket": self._bucket, "key": object_key, "size_bytes": len(data)},
            )
        return object_key

    async def download_file(self, object_key: str, file_path: Path) -> Path:
        """Download an object from MinIO to a local file.

        Args:
            object_key: S3 object key to download
            file_path: Local path to write the file

        Returns:
            The local file path
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        ) as s3:
            await s3.download_file(self._bucket, object_key, str(file_path))
            LOGGER.info(
                "file_downloaded",
                extra={"bucket": self._bucket, "key": object_key, "local_path": str(file_path)},
            )
        return file_path

    async def download_bytes(self, object_key: str) -> bytes:
        """Download an object from MinIO as bytes.

        Args:
            object_key: S3 object key to download

        Returns:
            The object data as bytes
        """
        async with self._session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        ) as s3:
            response = await s3.get_object(Bucket=self._bucket, Key=object_key)
            data: bytes = await response["Body"].read()
            LOGGER.info(
                "bytes_downloaded",
                extra={"bucket": self._bucket, "key": object_key, "size_bytes": len(data)},
            )
        return data

    @property
    def bucket(self) -> str:
        """The configured bucket name."""
        return self._bucket
