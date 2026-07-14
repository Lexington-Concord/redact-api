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
