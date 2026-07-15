"""Unit tests for the cheap structural pre-check ``validate_pdf_structure`` (redact-api#8).

``validate_pdf_structure`` is the fail-fast gate ``POST /jobs`` runs synchronously before
enqueuing ``ingest_job``. It must raise the exact same four ingest exceptions the full
``extract_pages`` path raises -- and never rasterize (no ``get_pixmap``).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from redact_api.ingest.consts import MAX_PAGE_COUNT
from redact_api.ingest.exceptions import (
    DocumentTooLargeError,
    EncryptedPdfError,
    MalformedPdfError,
    UnsupportedPageError,
)
from redact_api.ingest.pdf import validate_pdf_structure
from redact_api.tests.fixtures.ingest_pdfs import (
    build_encrypted_pdf,
    build_image_only_pdf,
    build_malformed_pdf,
    build_mixed_native_and_image_pdf,
    build_multi_page_pdf,
    build_oversized_page_count_pdf,
)


class TestValidatePdfStructure:
    def test_accepts_valid_native_pdf(self) -> None:
        # A structurally valid multi-page native PDF passes with no exception.
        validate_pdf_structure(build_multi_page_pdf(page_count=3))

    def test_rejects_malformed(self) -> None:
        with pytest.raises(MalformedPdfError):
            validate_pdf_structure(build_malformed_pdf())

    def test_rejects_encrypted(self) -> None:
        with pytest.raises(EncryptedPdfError):
            validate_pdf_structure(build_encrypted_pdf())

    def test_rejects_over_page_count(self) -> None:
        with pytest.raises(DocumentTooLargeError) as exc_info:
            validate_pdf_structure(build_oversized_page_count_pdf(MAX_PAGE_COUNT + 1))
        assert exc_info.value.limit_kind == "page_count"

    def test_rejects_image_only_page(self) -> None:
        with pytest.raises(UnsupportedPageError):
            validate_pdf_structure(build_image_only_pdf(page_count=1))

    def test_reports_all_unsupported_page_numbers(self) -> None:
        pdf_bytes = build_mixed_native_and_image_pdf(native_pages=1, image_pages=(2, 3))
        with pytest.raises(UnsupportedPageError) as exc_info:
            validate_pdf_structure(pdf_bytes)
        assert exc_info.value.page_numbers == [2, 3]

    def test_never_rasterizes(self) -> None:
        # The pre-check must be cheap: it must never call get_pixmap on any page.
        with patch("fitz.Page.get_pixmap") as mock_pixmap:
            validate_pdf_structure(build_multi_page_pdf(page_count=2))
        mock_pixmap.assert_not_called()
