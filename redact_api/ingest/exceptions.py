"""Typed exception hierarchy for the PDF ingest pipeline.

Every rejection raises one of the four subclasses below (never the bare
`IngestError` base) so callers -- and structured logging -- can discriminate
rejection reasons by type without parsing free-text messages. This is a
closed set: no fifth subclass should be added without revisiting the
ingest contract.
"""

from __future__ import annotations

from typing import Literal

LimitKind = Literal["file_size", "page_count"]


class IngestError(Exception):
    """Base exception for all PDF ingest rejections."""


class EncryptedPdfError(IngestError):
    """Raised when a PDF requires a password to open."""

    def __init__(self, message: str = "PDF is password-protected and cannot be ingested") -> None:
        self.message = message
        super().__init__(message)


class MalformedPdfError(IngestError):
    """Raised when a PDF cannot be parsed due to corruption or truncation."""

    def __init__(self, message: str = "PDF is malformed or corrupt and cannot be parsed") -> None:
        self.message = message
        super().__init__(message)


class UnsupportedPageError(IngestError):
    """Raised when one or more pages have no extractable text (e.g. scanned images).

    Attributes:
        page_numbers: 1-indexed page numbers with no extractable text.
    """

    def __init__(self, page_numbers: list[int]) -> None:
        self.page_numbers = page_numbers
        pages_str = ", ".join(str(page_number) for page_number in page_numbers)
        message = (
            f"Document contains scanned/image-only page(s) with no extractable text: {pages_str}; "
            "V1 supports native PDFs only -- OCR ingest is V2"
        )
        self.message = message
        super().__init__(message)


class DocumentTooLargeError(IngestError):
    """Raised when a document exceeds the file-size or page-count limit.

    A single class covers both limit kinds (rather than two separate
    exception classes) -- `limit_kind` distinguishes which limit was
    violated.

    Attributes:
        limit_kind: Which limit was violated -- "file_size" or "page_count".
        actual: The observed value (bytes or page count) that triggered rejection.
        limit: The configured maximum allowed value.
    """

    def __init__(self, limit_kind: LimitKind, actual: int, limit: int) -> None:
        self.limit_kind = limit_kind
        self.actual = actual
        self.limit = limit
        if limit_kind == "file_size":
            message = f"Document size {actual} bytes exceeds maximum allowed size of {limit} bytes"
        else:
            message = f"Document page count {actual} exceeds maximum allowed page count of {limit}"
        self.message = message
        super().__init__(message)
