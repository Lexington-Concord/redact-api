"""Tests for MinIO object key builders in redact_api.storage.keys.

Pure function tests -- no database, no network access.
"""

from uuid import UUID

from redact_api.storage import keys

DOCUMENT_ID = UUID("12345678-1234-5678-1234-567812345678")


class TestPageRasterKey:
    def test_returns_stable_key(self) -> None:
        key = keys.page_raster_key(DOCUMENT_ID, 1)
        assert key == keys.page_raster_key(DOCUMENT_ID, 1)

    def test_includes_document_id_and_page_number(self) -> None:
        key = keys.page_raster_key(DOCUMENT_ID, 3)
        assert str(DOCUMENT_ID) in key
        assert "3" in key

    def test_different_page_numbers_produce_different_keys(self) -> None:
        assert keys.page_raster_key(DOCUMENT_ID, 1) != keys.page_raster_key(DOCUMENT_ID, 2)

    def test_different_document_ids_produce_different_keys(self) -> None:
        other_id = UUID("87654321-4321-8765-4321-876543218765")
        assert keys.page_raster_key(DOCUMENT_ID, 1) != keys.page_raster_key(other_id, 1)

    def test_ends_with_png_extension(self) -> None:
        key = keys.page_raster_key(DOCUMENT_ID, 1)
        assert key.endswith(".png")


class TestPageTextLayerKey:
    def test_returns_stable_key(self) -> None:
        key = keys.page_text_layer_key(DOCUMENT_ID, 1)
        assert key == keys.page_text_layer_key(DOCUMENT_ID, 1)

    def test_includes_document_id_and_page_number(self) -> None:
        key = keys.page_text_layer_key(DOCUMENT_ID, 4)
        assert str(DOCUMENT_ID) in key
        assert "4" in key

    def test_ends_with_json_extension(self) -> None:
        key = keys.page_text_layer_key(DOCUMENT_ID, 1)
        assert key.endswith(".json")

    def test_distinct_from_raster_key(self) -> None:
        raster_key = keys.page_raster_key(DOCUMENT_ID, 1)
        text_layer_key = keys.page_text_layer_key(DOCUMENT_ID, 1)
        assert raster_key != text_layer_key


JOB_ID = UUID("abcdef00-0000-4000-8000-000000000000")


class TestOriginalPdfKey:
    def test_returns_stable_key(self) -> None:
        assert keys.original_pdf_key(DOCUMENT_ID) == keys.original_pdf_key(DOCUMENT_ID)

    def test_includes_document_id(self) -> None:
        assert str(DOCUMENT_ID) in keys.original_pdf_key(DOCUMENT_ID)

    def test_ends_with_pdf_extension(self) -> None:
        assert keys.original_pdf_key(DOCUMENT_ID).endswith(".pdf")

    def test_different_document_ids_produce_different_keys(self) -> None:
        other_id = UUID("87654321-4321-8765-4321-876543218765")
        assert keys.original_pdf_key(DOCUMENT_ID) != keys.original_pdf_key(other_id)

    def test_distinct_from_page_raster_key(self) -> None:
        assert keys.original_pdf_key(DOCUMENT_ID) != keys.page_raster_key(DOCUMENT_ID, 1)


class TestRedactedPdfKey:
    def test_returns_stable_key(self) -> None:
        assert keys.redacted_pdf_key(JOB_ID) == keys.redacted_pdf_key(JOB_ID)

    def test_includes_job_id(self) -> None:
        assert str(JOB_ID) in keys.redacted_pdf_key(JOB_ID)

    def test_ends_with_pdf_extension(self) -> None:
        assert keys.redacted_pdf_key(JOB_ID).endswith(".pdf")

    def test_different_job_ids_produce_different_keys(self) -> None:
        other_id = UUID("11111111-2222-3333-4444-555555555555")
        assert keys.redacted_pdf_key(JOB_ID) != keys.redacted_pdf_key(other_id)

    def test_distinct_from_original_pdf_key(self) -> None:
        # Same UUID used as both a document id and a job id must not collide.
        assert keys.redacted_pdf_key(JOB_ID) != keys.original_pdf_key(JOB_ID)
