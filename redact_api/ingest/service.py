"""Ingest orchestration: PDF bytes -> IngestResult, staged uploads to MinIO.

DB-free. `document_id` is caller-supplied and never persisted here -- this
module plays the "service" role for a future `redact_api/api/ingest.py`
router that doesn't exist yet.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from redact_api.core.config import settings
from redact_api.core.logging import get_logging_context
from redact_api.core.metrics import documents_ingested_total
from redact_api.ingest import pdf
from redact_api.ingest.exceptions import (
    DocumentTooLargeError,
    EncryptedPdfError,
    MalformedPdfError,
    UnsupportedPageError,
)
from redact_api.ingest.models import IngestResult, PageModel
from redact_api.ingest.pdf import PageExtraction
from redact_api.storage import keys
from redact_api.storage.client import StorageClient

LOGGER = logging.getLogger(__name__)


async def ingest_pdf(document_id: UUID, pdf_bytes: bytes, storage: StorageClient) -> IngestResult:
    """Extract a PDF's canonical page model and upload artifacts to MinIO.

    Validates file size and page count before any parsing; extraction itself
    validates encryption, corruption, and per-page text extractability.
    Uploads (raster PNG + text-layer JSON per page) only begin once every
    page has been extracted and validated -- no partial upload on rejection.

    Raises:
        DocumentTooLargeError: File size or page count exceeds the configured limit.
        EncryptedPdfError: PDF requires a password.
        MalformedPdfError: PDF cannot be parsed.
        UnsupportedPageError: One or more pages have no extractable text.
    """
    context = get_logging_context()
    LOGGER.info("ingest_started", extra={**context, "document_id": str(document_id)})

    try:
        _validate_file_size(pdf_bytes)
        extractions = pdf.extract_pages(pdf_bytes)
    except DocumentTooLargeError as error:
        LOGGER.warning(
            "ingest_rejected",
            extra={**context, "document_id": str(document_id), "error_type": type(error).__name__},
        )
        raise
    except EncryptedPdfError as error:
        LOGGER.warning(
            "ingest_rejected",
            extra={**context, "document_id": str(document_id), "error_type": type(error).__name__},
        )
        raise
    except MalformedPdfError as error:
        LOGGER.warning(
            "ingest_rejected",
            extra={**context, "document_id": str(document_id), "error_type": type(error).__name__},
        )
        raise
    except UnsupportedPageError as error:
        LOGGER.warning(
            "ingest_rejected",
            extra={**context, "document_id": str(document_id), "error_type": type(error).__name__},
        )
        raise

    pages = [await _upload_page(document_id, extraction, storage) for extraction in extractions]
    result = IngestResult(document_id=document_id, page_count=len(pages), pages=pages)

    documents_ingested_total.labels(environment=settings.environment).inc()
    LOGGER.info(
        "ingest_completed",
        extra={**context, "document_id": str(document_id), "page_count": result.page_count},
    )
    return result


def _validate_file_size(pdf_bytes: bytes) -> None:
    """Reject before any parsing if the raw upload exceeds the configured limit."""
    if len(pdf_bytes) > settings.max_file_size_bytes:
        raise DocumentTooLargeError(
            limit_kind="file_size",
            actual=len(pdf_bytes),
            limit=settings.max_file_size_bytes,
        )


async def _upload_page(document_id: UUID, extraction: PageExtraction, storage: StorageClient) -> PageModel:
    """Upload one page's raster + text-layer artifacts and return its finalized PageModel."""
    raster_key = keys.page_raster_key(document_id, extraction.page.page_number)
    text_layer_key = keys.page_text_layer_key(document_id, extraction.page.page_number)

    await storage.upload_bytes(raster_key, extraction.png_bytes)
    await storage.upload_bytes(text_layer_key, _text_layer_payload(extraction.page))

    return extraction.page.model_copy(update={"raster_key": raster_key})


def _text_layer_payload(page: PageModel) -> bytes:
    """JSON projection of a page's text layer, for persistence/audit only.

    Never read back by this module -- written purely as an artifact.
    """
    payload = {
        "page_number": page.page_number,
        "text": page.text,
        "words": [{"start": word.start, "end": word.end, "bbox": list(word.bbox)} for word in page.words],
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")
