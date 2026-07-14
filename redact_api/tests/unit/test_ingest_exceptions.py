"""Tests for the ingest exception hierarchy.

Unit tests -- no database access, no PDF parsing required.
"""

from redact_api.ingest.exceptions import (
    DocumentTooLargeError,
    EncryptedPdfError,
    IngestError,
    MalformedPdfError,
    UnsupportedPageError,
)


class TestExceptionHierarchy:
    """Every typed rejection is both an IngestError and an Exception."""

    def test_encrypted_pdf_error_is_ingest_error(self) -> None:
        error = EncryptedPdfError()
        assert isinstance(error, IngestError)
        assert isinstance(error, Exception)

    def test_malformed_pdf_error_is_ingest_error(self) -> None:
        error = MalformedPdfError()
        assert isinstance(error, IngestError)
        assert isinstance(error, Exception)

    def test_unsupported_page_error_is_ingest_error(self) -> None:
        error = UnsupportedPageError(page_numbers=[1])
        assert isinstance(error, IngestError)
        assert isinstance(error, Exception)

    def test_document_too_large_error_is_ingest_error(self) -> None:
        error = DocumentTooLargeError(limit_kind="file_size", actual=100, limit=50)
        assert isinstance(error, IngestError)
        assert isinstance(error, Exception)


class TestUnsupportedPageError:
    """UnsupportedPageError exposes offending page numbers and pinned wording."""

    def test_exposes_offending_page_numbers(self) -> None:
        error = UnsupportedPageError(page_numbers=[2, 5, 9])
        assert error.page_numbers == [2, 5, 9]

    def test_str_contains_offending_page_numbers(self) -> None:
        error = UnsupportedPageError(page_numbers=[2, 5, 9])
        message = str(error)
        assert "2" in message
        assert "5" in message
        assert "9" in message

    def test_str_contains_pinned_wording(self) -> None:
        error = UnsupportedPageError(page_numbers=[3])
        assert "no extractable text" in str(error)

    def test_single_offending_page(self) -> None:
        error = UnsupportedPageError(page_numbers=[7])
        assert error.page_numbers == [7]
        assert "7" in str(error)


class TestDocumentTooLargeError:
    """DocumentTooLargeError message differs between file-size and page-count violations."""

    def test_file_size_violation_message(self) -> None:
        error = DocumentTooLargeError(limit_kind="file_size", actual=100_000_000, limit=50_000_000)
        assert error.limit_kind == "file_size"
        assert error.actual == 100_000_000
        assert error.limit == 50_000_000
        assert "size" in str(error).lower()
        assert "100000000" in str(error)
        assert "50000000" in str(error)

    def test_page_count_violation_message(self) -> None:
        error = DocumentTooLargeError(limit_kind="page_count", actual=600, limit=500)
        assert error.limit_kind == "page_count"
        assert error.actual == 600
        assert error.limit == 500
        assert "page" in str(error).lower()
        assert "600" in str(error)
        assert "500" in str(error)

    def test_file_size_and_page_count_messages_differ(self) -> None:
        file_size_error = DocumentTooLargeError(limit_kind="file_size", actual=100, limit=50)
        page_count_error = DocumentTooLargeError(limit_kind="page_count", actual=100, limit=50)
        assert str(file_size_error) != str(page_count_error)

    def test_single_class_not_two(self) -> None:
        # R8/Adopted Assumption 5: one class with a limit_kind attribute,
        # not two separate exception classes.
        file_size_error = DocumentTooLargeError(limit_kind="file_size", actual=1, limit=1)
        page_count_error = DocumentTooLargeError(limit_kind="page_count", actual=1, limit=1)
        assert type(file_size_error) is type(page_count_error)
