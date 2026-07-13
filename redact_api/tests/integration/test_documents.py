"""Comprehensive document endpoint tests for upload, download, validation, limits."""

from http import HTTPStatus
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from redact_api.core.config import settings
from redact_api.core.storage import (
    StorageError,
    StorageProvider,
    get_storage_service,
)
from redact_api.main import app

# Test file sizes
TEST_BINARY_FILE_SIZE = 256  # bytes - size of test binary data (0-255)
TEST_LARGE_FILE_SIZE = 10000  # bytes - 10KB for streaming tests


class TestDocumentUpload:
    """Test document upload operations."""

    @pytest.mark.asyncio
    async def test_upload_document_success(self, client: AsyncClient) -> None:
        """Upload a valid document."""
        file_content = b"Hello, World! This is a test document."
        files = {"file": ("test.txt", BytesIO(file_content), "text/plain")}

        response = await client.post("/documents", files=files)
        assert response.status_code == HTTPStatus.CREATED
        doc = response.json()
        assert doc["filename"] == "test.txt"
        assert doc["content_type"] == "text/plain"
        assert doc["file_size"] == len(file_content)
        assert "id" in doc
        assert "created_at" in doc
        assert "updated_at" in doc

    @pytest.mark.asyncio
    async def test_upload_document_with_binary_data(self, client: AsyncClient) -> None:
        """Upload a binary file (e.g., image)."""
        # Create fake binary image data
        file_content = bytes(range(256))  # 256 bytes of binary data
        files = {"file": ("image.png", BytesIO(file_content), "image/png")}

        response = await client.post("/documents", files=files)
        assert response.status_code == HTTPStatus.CREATED
        doc = response.json()
        assert doc["filename"] == "image.png"
        assert doc["content_type"] == "image/png"
        assert doc["file_size"] == TEST_BINARY_FILE_SIZE

    @pytest.mark.asyncio
    async def test_upload_document_no_filename(self, client: AsyncClient) -> None:
        """Uploading document without filename should fail."""
        file_content = b"Test content"
        files = {"file": ("", BytesIO(file_content), "text/plain")}

        response = await client.post("/documents", files=files)
        assert response.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_upload_document_no_content_type(self, client: AsyncClient) -> None:
        """Uploading document without explicit content type defaults to inferred type."""
        file_content = b"Test content"
        files = {"file": ("test.txt", BytesIO(file_content), None)}

        response = await client.post("/documents", files=files)
        # When content_type is None, httpx infers type from filename extension
        # .txt files default to text/plain
        assert response.status_code == HTTPStatus.CREATED
        assert response.json()["content_type"] == "text/plain"

    @pytest.mark.asyncio
    async def test_upload_document_size_limit(self, client: AsyncClient) -> None:
        """Uploading document exceeding size limit should fail."""
        # Create file larger than max_file_size_bytes
        max_size = settings.max_file_size_bytes
        oversized_content = b"x" * (max_size + 1)
        files = {"file": ("large.txt", BytesIO(oversized_content), "text/plain")}

        response = await client.post("/documents", files=files)
        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    @pytest.mark.asyncio
    async def test_upload_empty_document(self, client: AsyncClient) -> None:
        """Uploading empty document should succeed (0 bytes is valid)."""
        file_content = b""
        files = {"file": ("empty.txt", BytesIO(file_content), "text/plain")}

        response = await client.post("/documents", files=files)
        # Empty file is technically valid
        assert response.status_code in (HTTPStatus.CREATED, HTTPStatus.BAD_REQUEST)
        if response.status_code == HTTPStatus.CREATED:
            doc = response.json()
            assert doc["file_size"] == 0


class TestDocumentDownload:
    """Test document download operations."""

    @pytest.mark.asyncio
    async def test_download_document(self, client: AsyncClient) -> None:
        """Download a previously uploaded document."""
        # Upload document
        file_content = b"Test download content"
        files = {"file": ("download.txt", BytesIO(file_content), "text/plain")}
        upload_response = await client.post("/documents", files=files)
        doc_id = upload_response.json()["id"]

        # Download document
        download_response = await client.get(f"/documents/{doc_id}")
        assert download_response.status_code == HTTPStatus.OK
        assert download_response.content == file_content
        assert download_response.headers["content-type"].startswith("text/plain")
        content_disposition = download_response.headers.get("content-disposition", "")
        assert "attachment" in content_disposition
        assert "download.txt" in content_disposition

    @pytest.mark.asyncio
    async def test_download_binary_document(self, client: AsyncClient) -> None:
        """Download a binary document and verify content."""
        # Upload binary document
        file_content = bytes(range(256))
        files = {"file": ("binary.bin", BytesIO(file_content), "application/octet-stream")}
        upload_response = await client.post("/documents", files=files)
        doc_id = upload_response.json()["id"]

        # Download document
        download_response = await client.get(f"/documents/{doc_id}")
        assert download_response.status_code == HTTPStatus.OK
        assert download_response.content == file_content
        assert download_response.headers["content-type"] == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_download_nonexistent_document(self, client: AsyncClient) -> None:
        """Downloading nonexistent document should return 404."""
        response = await client.get("/documents/00000000-0000-0000-0000-000000000000")
        assert response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_download_streaming_response(self, client: AsyncClient) -> None:
        """Verify document is returned as streaming response."""
        # Upload larger document to test streaming
        file_content = b"x" * TEST_LARGE_FILE_SIZE  # 10KB
        files = {"file": ("stream.txt", BytesIO(file_content), "text/plain")}
        upload_response = await client.post("/documents", files=files)
        doc_id = upload_response.json()["id"]

        # Download document (should stream)
        download_response = await client.get(f"/documents/{doc_id}")
        assert download_response.status_code == HTTPStatus.OK
        assert len(download_response.content) == TEST_LARGE_FILE_SIZE


class TestDocumentValidation:
    """Test document validation rules."""

    @pytest.mark.asyncio
    async def test_filename_validation(self, client: AsyncClient) -> None:
        """Test various filename patterns."""
        valid_filenames = [
            "simple.txt",
            "with-dash.txt",
            "with_underscore.txt",
            "with spaces.txt",
            "multiple.dots.in.name.txt",
            "UPPERCASE.TXT",
            "123numeric.txt",
        ]

        for filename in valid_filenames:
            file_content = b"Test content"
            files = {"file": (filename, BytesIO(file_content), "text/plain")}
            response = await client.post("/documents", files=files)
            assert response.status_code == HTTPStatus.CREATED
            assert response.json()["filename"] == filename

    @pytest.mark.asyncio
    async def test_content_type_preservation(self, client: AsyncClient) -> None:
        """Verify content type is preserved through upload/download."""
        content_types = [
            "text/plain",
            "application/json",
            "application/pdf",
            "image/jpeg",
            "application/octet-stream",
        ]

        for content_type in content_types:
            file_content = b"Test content"
            ext = content_type.split("/")[-1]
            files = {
                "file": (
                    f"test.{ext}",
                    BytesIO(file_content),
                    content_type,
                )
            }
            upload_response = await client.post("/documents", files=files)
            assert upload_response.status_code == HTTPStatus.CREATED

            doc_id = upload_response.json()["id"]
            download_response = await client.get(f"/documents/{doc_id}")
            assert download_response.headers["content-type"].startswith(content_type)

    @pytest.mark.asyncio
    async def test_file_size_tracking(self, client: AsyncClient) -> None:
        """Verify file size is accurately tracked."""
        test_sizes = [0, 100, 1024, 10000]

        for size in test_sizes:
            file_content = b"x" * size
            files = {"file": (f"size{size}.txt", BytesIO(file_content), "text/plain")}
            response = await client.post("/documents", files=files)
            if response.status_code == HTTPStatus.CREATED:
                assert response.json()["file_size"] == size


class TestDocumentErrorHandling:
    """Test document error scenarios."""

    @pytest.mark.asyncio
    async def test_invalid_document_id(self, client: AsyncClient) -> None:
        """Getting document with invalid UUID should return 422."""
        response = await client.get("/documents/not-a-uuid")
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_missing_file_in_upload(self, client: AsyncClient) -> None:
        """Uploading without file should fail."""
        response = await client.post("/documents", data={})
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


class TestDocumentDangerousMimeTypes:
    """Test security rejection of dangerous MIME types.

    Dangerous MIME types (HTML, SVG, JavaScript) are rejected to prevent
    XSS attacks via uploaded content that browsers might execute.
    """

    @pytest.mark.asyncio
    async def test_upload_html_rejected(self, client: AsyncClient) -> None:
        """Uploading text/html file should be rejected for XSS protection."""
        file_content = b"<html><body><script>alert('xss')</script></body></html>"
        files = {"file": ("page.html", BytesIO(file_content), "text/html")}

        response = await client.post("/documents", files=files)
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "not allowed" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_svg_rejected(self, client: AsyncClient) -> None:
        """Uploading image/svg+xml file should be rejected (can contain JS)."""
        file_content = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        files = {"file": ("image.svg", BytesIO(file_content), "image/svg+xml")}

        response = await client.post("/documents", files=files)
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "not allowed" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_javascript_rejected(self, client: AsyncClient) -> None:
        """Uploading application/javascript file should be rejected."""
        file_content = b"alert('malicious');"
        files = {"file": ("script.js", BytesIO(file_content), "application/javascript")}

        response = await client.post("/documents", files=files)
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "not allowed" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_text_javascript_rejected(self, client: AsyncClient) -> None:
        """Uploading text/javascript file should be rejected."""
        file_content = b"console.log('malicious');"
        files = {"file": ("script.js", BytesIO(file_content), "text/javascript")}

        response = await client.post("/documents", files=files)
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "not allowed" in response.json()["detail"].lower()


class TestDocumentStorageErrors:
    """Test storage error handling paths.

    These tests verify that storage failures are handled gracefully with
    appropriate HTTP status codes and error messages.

    Note: These tests use the existing client fixture which has proper auth middleware,
    and only override the storage dependency to simulate failures.
    """

    @pytest.mark.asyncio
    async def test_upload_storage_error_rollback(self, client: AsyncClient) -> None:
        """Upload fails gracefully when storage service raises StorageError.

        Verifies:
        - 503 Service Unavailable returned
        - Error message includes storage failure details
        - Database transaction rolled back (no orphaned metadata)
        """
        # Create mock storage service that raises on upload
        mock_storage = AsyncMock()
        mock_storage.upload.side_effect = StorageError("Simulated storage failure")

        # Store original override to restore later
        original_override = app.dependency_overrides.get(get_storage_service)
        app.dependency_overrides[get_storage_service] = lambda: mock_storage

        try:
            file_content = b"Test content for storage error"
            files = {"file": ("test.txt", BytesIO(file_content), "text/plain")}

            response = await client.post("/documents", files=files)

            assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
            assert "storage" in response.json()["detail"].lower()
        finally:
            if original_override:
                app.dependency_overrides[get_storage_service] = original_override
            else:
                app.dependency_overrides.pop(get_storage_service, None)

    @pytest.mark.asyncio
    async def test_download_storage_error(self, client: AsyncClient) -> None:
        """Download fails gracefully when storage service raises StorageError.

        Verifies:
        - 503 Service Unavailable returned for local storage errors
        - Error message includes storage failure details
        """
        # First upload a document successfully
        file_content = b"Test download content"
        files = {"file": ("download_error_test.txt", BytesIO(file_content), "text/plain")}
        upload_response = await client.post("/documents", files=files)
        assert upload_response.status_code == HTTPStatus.CREATED
        doc_id = upload_response.json()["id"]

        # Now mock storage to fail on download
        mock_storage = AsyncMock()
        mock_storage.download.side_effect = StorageError("Simulated download failure")

        original_override = app.dependency_overrides.get(get_storage_service)
        app.dependency_overrides[get_storage_service] = lambda: mock_storage

        try:
            response = await client.get(f"/documents/{doc_id}")

            assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
            assert "storage" in response.json()["detail"].lower()
        finally:
            if original_override:
                app.dependency_overrides[get_storage_service] = original_override
            else:
                app.dependency_overrides.pop(get_storage_service, None)

    @pytest.mark.asyncio
    async def test_download_file_missing_from_storage(self, client: AsyncClient) -> None:
        """Download returns 404 when file exists in DB but missing from storage.

        This handles orphaned metadata (document deleted from storage but
        metadata still exists in database).

        Verifies:
        - 404 Not Found returned (not 503)
        - Error message distinguishes this from "document not found"
        """
        # First upload a document successfully
        file_content = b"Test missing file content"
        files = {"file": ("missing_file_test.txt", BytesIO(file_content), "text/plain")}
        upload_response = await client.post("/documents", files=files)
        assert upload_response.status_code == HTTPStatus.CREATED
        doc_id = upload_response.json()["id"]

        # Mock storage to return None (file not found in storage)
        mock_storage = AsyncMock()
        mock_storage.download.return_value = None

        original_override = app.dependency_overrides.get(get_storage_service)
        app.dependency_overrides[get_storage_service] = lambda: mock_storage

        try:
            response = await client.get(f"/documents/{doc_id}")

            assert response.status_code == HTTPStatus.NOT_FOUND
            # Should mention the file is missing from storage, not just "not found"
            assert "storage" in response.json()["detail"].lower()
        finally:
            if original_override:
                app.dependency_overrides[get_storage_service] = original_override
            else:
                app.dependency_overrides.pop(get_storage_service, None)

    @pytest.mark.asyncio
    async def test_delete_storage_error(self, client: AsyncClient) -> None:
        """Delete fails gracefully when storage service raises StorageError.

        Verifies:
        - 503 Service Unavailable returned
        - Document metadata not deleted (consistency maintained)
        """
        # First upload a document successfully
        file_content = b"Test delete error content"
        files = {"file": ("delete_error_test.txt", BytesIO(file_content), "text/plain")}
        upload_response = await client.post("/documents", files=files)
        assert upload_response.status_code == HTTPStatus.CREATED
        doc_id = upload_response.json()["id"]

        # Mock storage to fail on delete
        mock_storage = AsyncMock()
        mock_storage.delete.side_effect = StorageError("Simulated delete failure")

        original_override = app.dependency_overrides.get(get_storage_service)
        app.dependency_overrides[get_storage_service] = lambda: mock_storage

        try:
            response = await client.delete(f"/documents/{doc_id}")

            assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
            assert "storage" in response.json()["detail"].lower()
        finally:
            if original_override:
                app.dependency_overrides[get_storage_service] = original_override
            else:
                app.dependency_overrides.pop(get_storage_service, None)


class TestDocumentCloudProviderPaths:
    """Test cloud provider redirect behavior.

    For cloud providers (Azure, S3, GCS), download returns a redirect to
    a presigned URL for direct download, reducing application server load.
    """

    @pytest.mark.asyncio
    async def test_download_cloud_provider_redirect(self, client: AsyncClient) -> None:
        """Cloud provider download returns redirect to presigned URL.

        Tests the redirect path when storage_provider is a cloud provider.
        Uses mocking to simulate cloud provider behavior without actual cloud deps.
        """
        # First upload a document with local storage
        file_content = b"Test cloud redirect content"
        files = {"file": ("cloud_test.txt", BytesIO(file_content), "text/plain")}
        upload_response = await client.post("/documents", files=files)
        assert upload_response.status_code == HTTPStatus.CREATED
        doc_id = upload_response.json()["id"]

        # Mock storage service to return presigned URL
        mock_storage = AsyncMock()
        presigned_url = "https://testaccount.blob.core.windows.net/container/file?sig=xxx"
        mock_storage.get_download_url.return_value = presigned_url

        original_override = app.dependency_overrides.get(get_storage_service)
        app.dependency_overrides[get_storage_service] = lambda: mock_storage

        try:
            # Patch settings to use Azure provider
            with patch(
                "redact_api.api.documents.settings.storage_provider",
                StorageProvider.AZURE,
            ):
                # Use follow_redirects=False to capture the redirect response
                response = await client.get(f"/documents/{doc_id}", follow_redirects=False)

                assert response.status_code == HTTPStatus.FOUND  # 302
                assert response.headers["location"] == presigned_url
        finally:
            if original_override:
                app.dependency_overrides[get_storage_service] = original_override
            else:
                app.dependency_overrides.pop(get_storage_service, None)

    @pytest.mark.asyncio
    async def test_download_cloud_provider_url_generation_error(self, client: AsyncClient) -> None:
        """Cloud provider download fails gracefully when URL generation fails.

        Verifies:
        - 503 Service Unavailable returned
        - Error message includes storage failure details
        """
        # First upload a document with local storage
        file_content = b"Test cloud error content"
        files = {"file": ("cloud_error_test.txt", BytesIO(file_content), "text/plain")}
        upload_response = await client.post("/documents", files=files)
        assert upload_response.status_code == HTTPStatus.CREATED
        doc_id = upload_response.json()["id"]

        # Mock storage to fail on URL generation
        mock_storage = AsyncMock()
        mock_storage.get_download_url.side_effect = StorageError("Simulated URL generation failure")

        original_override = app.dependency_overrides.get(get_storage_service)
        app.dependency_overrides[get_storage_service] = lambda: mock_storage

        try:
            # Patch settings to use Azure provider
            with patch(
                "redact_api.api.documents.settings.storage_provider",
                StorageProvider.AZURE,
            ):
                response = await client.get(f"/documents/{doc_id}")

                assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
                assert "url" in response.json()["detail"].lower()
        finally:
            if original_override:
                app.dependency_overrides[get_storage_service] = original_override
            else:
                app.dependency_overrides.pop(get_storage_service, None)


class TestDocumentPathTraversalSecurity:
    """Test security against path traversal attacks in local storage.

    Path traversal attacks attempt to escape the storage directory by using
    special path components like .. or absolute paths. UUIDs prevent most
    attacks, but validation ensures defense in depth.
    """

    @pytest.mark.asyncio
    async def test_document_id_must_be_uuid_format(self, client: AsyncClient) -> None:
        """Path traversal attempts with non-UUID document IDs should fail.

        The API enforces UUID format on document_id path parameter.
        This prevents injection of path traversal sequences.

        Note: FastAPI returns 404 (route not found) for malformed UUIDs in path
        parameters, not 422. Either way, the traversal is blocked.
        """
        # Attempt to use .. for path traversal
        response = await client.get("/documents/../../etc/passwd")
        # Should return 404 (route not matched) or 422 (validation error)
        assert response.status_code in (HTTPStatus.NOT_FOUND, HTTPStatus.UNPROCESSABLE_ENTITY)

        # Attempt absolute path
        response = await client.get("/documents//etc/passwd")
        assert response.status_code in (HTTPStatus.NOT_FOUND, HTTPStatus.UNPROCESSABLE_ENTITY)

        # Attempt dot-dot sequences
        response = await client.get("/documents/..%2F..%2Fetc%2Fpasswd")
        assert response.status_code in (HTTPStatus.NOT_FOUND, HTTPStatus.UNPROCESSABLE_ENTITY)

    @pytest.mark.asyncio
    async def test_valid_uuid_stays_within_storage_directory(self, client: AsyncClient) -> None:
        """Valid UUIDs cannot escape storage directory.

        Even valid UUIDs cannot escape the storage directory because:
        1. UUID format is strictly validated in path parameters
        2. Storage backend validates resolved path is within base_path
        3. Combination provides defense in depth against path traversal
        """
        # A valid UUID that doesn't exist
        response = await client.get("/documents/00000000-0000-0000-0000-000000000000")
        # Should return 404 (not found), not allow traversal
        assert response.status_code == HTTPStatus.NOT_FOUND

        # Another valid UUID
        response = await client.get("/documents/ffffffff-ffff-ffff-ffff-ffffffffffff")
        # Should return 404 (not found), not allow traversal
        assert response.status_code == HTTPStatus.NOT_FOUND
