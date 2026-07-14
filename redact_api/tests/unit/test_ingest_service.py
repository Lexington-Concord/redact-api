"""Orchestration tests for redact_api.ingest.service.ingest_pdf.

Unit tests -- no database access. Uses a fake in-memory StorageClient double
(subclassing the real StorageClient so isinstance/type checks still hold,
with upload_bytes overridden to record in memory instead of hitting MinIO).
"""

from __future__ import annotations

import json
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from redact_api.core.metrics import documents_ingested_total
from redact_api.ingest import service
from redact_api.ingest.exceptions import (
    DocumentTooLargeError,
    EncryptedPdfError,
    MalformedPdfError,
    UnsupportedPageError,
)
from redact_api.ingest.service import ingest_pdf
from redact_api.storage import keys
from redact_api.storage.client import StorageClient
from redact_api.tests.fixtures.ingest_pdfs import (
    build_encrypted_pdf,
    build_malformed_pdf,
    build_mixed_native_and_image_pdf,
    build_multi_page_pdf,
    build_non_ascii_pdf,
    build_oversized_page_count_pdf,
)

DOCUMENT_ID = UUID("11111111-2222-3333-4444-555555555555")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class FakeStorageClient(StorageClient):
    """In-memory StorageClient double: records uploads instead of hitting MinIO."""

    def __init__(self) -> None:
        super().__init__(access_key="fake-access", secret_key="fake-secret", bucket="fake-bucket")
        self.uploads: dict[str, bytes] = {}
        self.content_types: dict[str, str | None] = {}

    async def upload_bytes(self, object_key: str, data: bytes, *, content_type: str | None = None) -> str:
        self.uploads[object_key] = data
        self.content_types[object_key] = content_type
        return object_key


@pytest.fixture
def fake_storage() -> FakeStorageClient:
    return FakeStorageClient()


def _unique_environment(name: str) -> str:
    return f"test_ingest_{name}_{uuid4().hex[:8]}"


class TestIngestPdfHappyPath:
    @pytest.mark.anyio
    async def test_returns_ingest_result_with_raster_keys(self, fake_storage: FakeStorageClient) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=2)

        result = await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        assert result.page_count == 2
        assert len(result.pages) == 2
        for page in result.pages:
            assert page.raster_key == keys.page_raster_key(DOCUMENT_ID, page.page_number)

    @pytest.mark.anyio
    async def test_uploads_raster_and_text_layer_per_page(self, fake_storage: FakeStorageClient) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=2)

        await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        assert len(fake_storage.uploads) == 4  # 2 pages * (raster + text-layer)
        for page_number in (1, 2):
            raster_key = keys.page_raster_key(DOCUMENT_ID, page_number)
            text_layer_key = keys.page_text_layer_key(DOCUMENT_ID, page_number)
            assert fake_storage.uploads[raster_key].startswith(PNG_MAGIC)
            assert fake_storage.content_types[raster_key] == "image/png"
            payload = json.loads(fake_storage.uploads[text_layer_key])
            assert payload["page_number"] == page_number
            assert isinstance(payload["text"], str)
            assert isinstance(payload["words"], list)
            assert fake_storage.content_types[text_layer_key] == "application/json"

    @pytest.mark.anyio
    async def test_text_layer_json_schema(self, fake_storage: FakeStorageClient) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=1)

        result = await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        text_layer_key = keys.page_text_layer_key(DOCUMENT_ID, 1)
        payload = json.loads(fake_storage.uploads[text_layer_key])
        assert payload["page_number"] == 1
        assert payload["text"] == result.pages[0].text
        assert len(payload["words"]) == len(result.pages[0].words)
        for word_payload, word_model in zip(payload["words"], result.pages[0].words, strict=True):
            assert word_payload["start"] == word_model.start
            assert word_payload["end"] == word_model.end
            assert word_payload["bbox"] == list(word_model.bbox)

    @pytest.mark.anyio
    async def test_increments_documents_ingested_counter(
        self, fake_storage: FakeStorageClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        environment = _unique_environment("counter")
        monkeypatch.setattr(service.settings, "environment", environment)
        counter = documents_ingested_total.labels(environment=environment)
        before = counter._value.get()

        pdf_bytes = build_multi_page_pdf(page_count=1)
        await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        after = counter._value.get()
        assert after == before + 1


class TestIngestPdfRejections:
    @pytest.mark.anyio
    async def test_encrypted_pdf_raises_and_uploads_nothing(self, fake_storage: FakeStorageClient) -> None:
        pdf_bytes = build_encrypted_pdf()

        with pytest.raises(EncryptedPdfError):
            await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        assert fake_storage.uploads == {}

    @pytest.mark.anyio
    async def test_malformed_pdf_raises_and_uploads_nothing(self, fake_storage: FakeStorageClient) -> None:
        pdf_bytes = build_malformed_pdf()

        with pytest.raises(MalformedPdfError):
            await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        assert fake_storage.uploads == {}

    @pytest.mark.anyio
    async def test_mixed_native_and_image_raises_naming_offending_page(
        self, fake_storage: FakeStorageClient
    ) -> None:
        pdf_bytes = build_mixed_native_and_image_pdf(native_pages=2, image_pages=(2,))

        with pytest.raises(UnsupportedPageError) as exc_info:
            await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        assert exc_info.value.page_numbers == [2]
        assert fake_storage.uploads == {}

    @pytest.mark.anyio
    async def test_oversized_file_raises_before_any_parsing_or_upload(
        self, fake_storage: FakeStorageClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(service.settings, "max_file_size_bytes", 10)
        pdf_bytes = build_multi_page_pdf(page_count=1)
        assert len(pdf_bytes) > 10

        with pytest.raises(DocumentTooLargeError) as exc_info:
            await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        assert exc_info.value.limit_kind == "file_size"
        assert fake_storage.uploads == {}

    @pytest.mark.anyio
    async def test_oversized_page_count_raises_naming_actual_vs_max(self, fake_storage: FakeStorageClient) -> None:
        pdf_bytes = build_oversized_page_count_pdf(page_count=501)

        with pytest.raises(DocumentTooLargeError) as exc_info:
            await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        assert exc_info.value.limit_kind == "page_count"
        assert exc_info.value.actual == 501
        assert exc_info.value.limit == 500
        assert fake_storage.uploads == {}


class TestIngestPdfNonAsciiRoundTrip:
    @pytest.mark.anyio
    async def test_non_ascii_text_round_trips_through_storage(self, fake_storage: FakeStorageClient) -> None:
        pdf_bytes = build_non_ascii_pdf()

        result = await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        text_layer_key = keys.page_text_layer_key(DOCUMENT_ID, 1)
        payload = json.loads(fake_storage.uploads[text_layer_key])
        assert payload["text"] == result.pages[0].text
        assert "café" in payload["text"]
        assert "日本語" in payload["text"]
        assert "ñ" in payload["text"]


class TestIngestPdfLogging:
    """Assert on redact_api.ingest.service.LOGGER directly (patched), matching the
    mock-the-module-LOGGER idiom used in redact_api/tests/unit/test_logging.py --
    more robust than caplog, which is sensitive to logger/handler state set up
    elsewhere in the full test suite (app lifespan, other modules' logging config).
    """

    @pytest.mark.anyio
    async def test_logs_started_and_completed_on_success(self, fake_storage: FakeStorageClient) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=2)

        with patch("redact_api.ingest.service.LOGGER") as mock_logger:
            await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        started = [c for c in mock_logger.info.call_args_list if c.args[0] == "ingest_started"]
        completed = [c for c in mock_logger.info.call_args_list if c.args[0] == "ingest_completed"]
        assert len(started) == 1
        assert len(completed) == 1
        assert completed[0].kwargs["extra"]["page_count"] == 2

    @pytest.mark.anyio
    async def test_logs_rejected_at_warning_with_error_type(self, fake_storage: FakeStorageClient) -> None:
        pdf_bytes = build_encrypted_pdf()

        with patch("redact_api.ingest.service.LOGGER") as mock_logger, pytest.raises(EncryptedPdfError):
            await ingest_pdf(DOCUMENT_ID, pdf_bytes, fake_storage)

        mock_logger.warning.assert_called_once()
        call = mock_logger.warning.call_args
        assert call.args[0] == "ingest_rejected"
        assert call.kwargs["extra"]["error_type"] == "EncryptedPdfError"

    @pytest.mark.anyio
    async def test_logs_rejected_for_each_typed_rejection(
        self, fake_storage: FakeStorageClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cases: list[tuple[bytes, str]] = [
            (build_encrypted_pdf(), "EncryptedPdfError"),
            (build_malformed_pdf(), "MalformedPdfError"),
            (build_mixed_native_and_image_pdf(native_pages=1, image_pages=(2,)), "UnsupportedPageError"),
        ]

        for pdf_bytes, expected_error_type in cases:
            with (
                patch("redact_api.ingest.service.LOGGER") as mock_logger,
                pytest.raises((EncryptedPdfError, MalformedPdfError, UnsupportedPageError)),
            ):
                await ingest_pdf(uuid4(), pdf_bytes, fake_storage)
            mock_logger.warning.assert_called_once()
            assert mock_logger.warning.call_args.kwargs["extra"]["error_type"] == expected_error_type

        monkeypatch.setattr(service.settings, "max_file_size_bytes", 10)
        with patch("redact_api.ingest.service.LOGGER") as mock_logger, pytest.raises(DocumentTooLargeError):
            await ingest_pdf(uuid4(), build_multi_page_pdf(page_count=1), fake_storage)
        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args.kwargs["extra"]["error_type"] == "DocumentTooLargeError"
