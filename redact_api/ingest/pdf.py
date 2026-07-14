"""PyMuPDF-based PDF ingest: page-model extraction (raster + word bboxes).

Word/text extraction is a single pass per page: `page.get_text("words")` is
the only text-extraction API called here -- never `"text"`/`"dict"`/
`"rawdict"` in the same code path -- so `PageModel.text` offsets can never
desync from `PageModel.words`: both are built from the same buffer in the
same loop (`_build_text_and_words`).
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz

from redact_api.ingest.consts import MAX_PAGE_COUNT, RASTER_DPI
from redact_api.ingest.exceptions import (
    DocumentTooLargeError,
    EncryptedPdfError,
    MalformedPdfError,
    UnsupportedPageError,
)
from redact_api.ingest.models import PageModel, WordBBox

_WORD_JOIN = " "
_LINE_JOIN = "\n"

# `page.get_text("words")` returns 8-tuples:
# (x0, y0, x1, y1, word_text, block_no, line_no, word_no)
_RawWord = tuple[float, float, float, float, str, int, int, int]


@dataclass(frozen=True)
class PageExtraction:
    """Raw per-page extraction output, prior to storage-key assignment.

    `page.raster_key` is an empty-string placeholder here -- `service.py`
    fills it in (via `page.model_copy(update=...)`) once a `document_id` is
    known and the raster has been uploaded.
    """

    page: PageModel
    png_bytes: bytes


def extract_pages(pdf_bytes: bytes) -> list[PageExtraction]:
    """Extract the canonical page model for every page of a PDF.

    Raises:
        MalformedPdfError: If the PDF cannot be opened/parsed.
        EncryptedPdfError: If the PDF requires a password.
        DocumentTooLargeError: If the page count exceeds MAX_PAGE_COUNT.
        UnsupportedPageError: If one or more pages have no extractable text.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except (fitz.FileDataError, RuntimeError) as exc:
        message = "PDF is malformed or corrupt and cannot be opened"
        raise MalformedPdfError(message) from exc

    try:
        return _extract_open_document(doc)
    finally:
        doc.close()


def _extract_open_document(doc: fitz.Document) -> list[PageExtraction]:
    if doc.needs_pass:
        raise EncryptedPdfError

    if doc.page_count > MAX_PAGE_COUNT:
        raise DocumentTooLargeError(limit_kind="page_count", actual=doc.page_count, limit=MAX_PAGE_COUNT)

    extractions: list[PageExtraction] = []
    unsupported_page_numbers: list[int] = []

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        extraction = _extract_page(page, page_index + 1)
        if not extraction.page.words:
            unsupported_page_numbers.append(extraction.page.page_number)
        extractions.append(extraction)

    if unsupported_page_numbers:
        raise UnsupportedPageError(unsupported_page_numbers)

    return extractions


def _extract_page(page: fitz.Page, page_number: int) -> PageExtraction:
    raw_words = sorted(page.get_text("words"), key=lambda word: (word[5], word[6], word[7]))
    text, words = _build_text_and_words(raw_words)

    pixmap = page.get_pixmap(matrix=fitz.Matrix(RASTER_DPI / 72, RASTER_DPI / 72))
    png_bytes = pixmap.tobytes("png")

    page_model = PageModel(
        page_number=page_number,
        width=page.rect.width,
        height=page.rect.height,
        text=text,
        words=words,
        rotation=page.rotation,
        raster_key="",
    )
    return PageExtraction(page=page_model, png_bytes=png_bytes)


def _build_text_and_words(raw_words: list[_RawWord]) -> tuple[str, list[WordBBox]]:
    """Build page text and word bboxes from a single sorted word list.

    Same-line words (matching block_no/line_no) are joined by a single ASCII
    space; a block/line boundary is joined by a single newline; there is no
    trailing separator after the last word.
    """
    text_buffer: list[str] = []
    words: list[WordBBox] = []
    offset = 0

    for index, raw_word in enumerate(raw_words):
        x0, y0, x1, y1, word_text, block_no, line_no, _word_no = raw_word

        start = offset
        end = start + len(word_text)
        words.append(WordBBox(start=start, end=end, bbox=(x0, y0, x1, y1)))
        text_buffer.append(word_text)
        offset = end

        if index < len(raw_words) - 1:
            next_block_no, next_line_no = raw_words[index + 1][5], raw_words[index + 1][6]
            same_line = (block_no, line_no) == (next_block_no, next_line_no)
            separator = _WORD_JOIN if same_line else _LINE_JOIN
            text_buffer.append(separator)
            offset += len(separator)

    return "".join(text_buffer), words
