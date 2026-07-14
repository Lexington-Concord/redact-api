"""Programmatic PyMuPDF-based PDF fixture builders for ingest tests.

All fixtures are built using PyMuPDF itself (no second PDF-writing library),
so tests exercise the same document model the ingest pipeline parses.

Fixture pages default to US Letter (612x792 pt). Combined with
``RASTER_DPI = 150`` (see ``redact_api.ingest.consts``), that makes rasterized
pixel dimensions land on exact integers in both orientations -- 612*150/72 and
792*150/72 are both whole numbers -- which avoids depending on whether
PyMuPDF's internal pixel-sizing rounds or ceils a fractional DPI-scaled
dimension (verified empirically: it ceils, not rounds, when fractional).
"""

from __future__ import annotations

import io
import re

import fitz

PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0

# Matches CJK ideographs, hiragana/katakana, and hangul -- used to pick a
# builtin PyMuPDF font (Base-14 "helv" vs builtin CJK "japan") per text run,
# since no single Base-14 font covers both Latin-1 and CJK glyphs.
_CJK_CHAR_PATTERN = re.compile(r"[一-鿿぀-ヿ가-힯]")

_IMAGE_RECT = fitz.Rect(72, 72, 272, 272)


def _new_letter_page(doc: fitz.Document) -> fitz.Page:
    """Add a new US Letter (612x792 pt) page to `doc`."""
    return doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)


def _blank_pixmap(width: int = 100, height: int = 100, color: tuple[int, int, int] = (200, 200, 200)) -> fitz.Pixmap:
    """A solid-color RGB pixmap, used to build image-only pages."""
    pixmap = fitz.Pixmap(fitz.csRGB, (0, 0, width, height), False)
    pixmap.set_rect(pixmap.irect, color)
    return pixmap


def _split_by_script(text: str) -> list[str]:
    """Split `text` into contiguous CJK / non-CJK runs for per-run font selection."""
    segments: list[str] = []
    current = ""
    current_is_cjk: bool | None = None
    for char in text:
        is_cjk = bool(_CJK_CHAR_PATTERN.match(char))
        if current_is_cjk is None or is_cjk == current_is_cjk:
            current += char
        else:
            segments.append(current)
            current = char
        current_is_cjk = is_cjk
    if current:
        segments.append(current)
    return segments


def build_multi_page_pdf(page_count: int = 3) -> bytes:
    """A PDF with `page_count` pages, each with multi-word, multi-line native text."""
    doc = fitz.open()
    for page_index in range(page_count):
        page = _new_letter_page(doc)
        page.insert_text((72, 72), f"Page {page_index + 1} heading line", fontsize=12)
        page.insert_text((72, 100), "Second line of body text here", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def build_pii_sample_pdf() -> bytes:
    """A single-page PDF whose native text embeds one instance of each Tier-1 category.

    Used by the detection end-to-end test to exercise the detectors against real
    ``extract_pages`` output (reconstructed ``PageModel.text`` + ``WordBBox``
    offsets), not hand-built pages. Each PII value sits on its own line, and the
    DOB line keeps its keyword anchor on the same line as the date.
    """
    lines = [
        "SSN 123-45-6789",
        "Call 212-555-0142 today",
        "Email jane.doe@example.com",
        "Account 4242424242424242",
        "Plate ABC1234",
        "DOB: 01/02/1990",
    ]
    doc = fitz.open()
    page = _new_letter_page(doc)
    y = 72.0
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 28.0
    data = doc.tobytes()
    doc.close()
    return data


def build_rotated_page_pdf(rotation: int = 90) -> bytes:
    """A single-page PDF with the given page rotation applied."""
    doc = fitz.open()
    page = _new_letter_page(doc)
    page.insert_text((72, 72), "Rotated page content", fontsize=12)
    page.set_rotation(rotation)
    data = doc.tobytes()
    doc.close()
    return data


def build_non_ascii_pdf(text: str = "café - 日本語 - ñ") -> bytes:
    """A single-page PDF containing Latin-1 and CJK text.

    `text` is split into contiguous same-script runs and each run is
    rendered on its own line with a font that covers its script (Base-14
    "helv" for Latin, builtin "japan" for CJK) -- no single Base-14 font
    covers both, and picking the wrong one silently substitutes a fallback
    glyph, which would desync the extracted text from `text`.
    """
    doc = fitz.open()
    page = _new_letter_page(doc)
    y = 72.0
    for segment in _split_by_script(text):
        if not segment.strip():
            continue
        fontname = "japan" if _CJK_CHAR_PATTERN.search(segment) else "helv"
        page.insert_text((72, y), segment, fontsize=12, fontname=fontname)
        y += 28.0
    data = doc.tobytes()
    doc.close()
    return data


def build_encrypted_pdf(user_password: str = "secret") -> bytes:
    """A single-page, password-protected PDF (AES-256, requires `user_password`)."""
    doc = fitz.open()
    page = _new_letter_page(doc)
    page.insert_text((72, 72), "Encrypted document content", fontsize=12)
    buffer = io.BytesIO()
    permissions = int(fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY | fitz.PDF_PERM_ANNOTATE)
    doc.save(
        buffer,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw=user_password,
        owner_pw=f"{user_password}-owner",
        permissions=permissions,
    )
    doc.close()
    return buffer.getvalue()


def build_malformed_pdf() -> bytes:
    """A PDF truncated mid-stream so `fitz.open()` raises `FileDataError`.

    Truncating to half the byte stream reliably destroys the xref/trailer
    while still leaving a `%PDF-` header, which is what actually causes
    PyMuPDF to raise at open time (verified empirically -- truncating a
    valid single-page PDF at 70% or above still opens fine; at 50% and
    below it consistently raises `FileDataError`).
    """
    doc = fitz.open()
    page = _new_letter_page(doc)
    page.insert_text((72, 72), "This document will be truncated mid-stream to corrupt it", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data[: len(data) // 2]


def build_image_only_pdf(page_count: int = 1) -> bytes:
    """A PDF with `page_count` pages that each contain only a raster image (no text)."""
    doc = fitz.open()
    for _ in range(page_count):
        page = _new_letter_page(doc)
        page.insert_image(_IMAGE_RECT, pixmap=_blank_pixmap())
    data = doc.tobytes()
    doc.close()
    return data


def build_mixed_native_and_image_pdf(
    native_pages: int = 2,
    image_pages: tuple[int, ...] = (2,),
) -> bytes:
    """A PDF mixing native-text pages with image-only pages.

    `image_pages` gives the 1-indexed page positions (within the final,
    combined document) that should be image-only; every other position is a
    native-text page. Total page count is `native_pages + len(image_pages)`.
    """
    total_pages = native_pages + len(image_pages)
    image_positions = set(image_pages)
    doc = fitz.open()
    native_counter = 0
    for position in range(1, total_pages + 1):
        page = _new_letter_page(doc)
        if position in image_positions:
            page.insert_image(_IMAGE_RECT, pixmap=_blank_pixmap())
        else:
            native_counter += 1
            page.insert_text((72, 72), f"Native page {native_counter} content", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def build_oversized_page_count_pdf(page_count: int) -> bytes:
    """A blank-page PDF with exactly `page_count` pages (for MAX_PAGE_COUNT tests)."""
    doc = fitz.open()
    for _ in range(page_count):
        _new_letter_page(doc)
    data = doc.tobytes()
    doc.close()
    return data
