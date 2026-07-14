"""Sanity tests for the redaction PDF fixture builders.

These builders are the oracle the verify-gate tests trust, so before relying on them
we prove each one actually encodes the failure mode it claims: the overlay fixture
really keeps a live text layer, the metadata fixture really leaks into docinfo/XMP, the
translucent fixture really has no text layer yet rasterizes to legible text, and the
control really is clean on all three axes.
"""

from __future__ import annotations

import io

import fitz
import pytesseract
import pytest
from PIL import Image
from rapidfuzz import fuzz

from redact_api.redaction.consts import OCR_MATCH_THRESHOLD, OCR_RASTER_DPI
from redact_api.redaction.verify_gate import normalize_text
from redact_api.tests.fixtures.redaction_pdfs import (
    DEFAULT_REDACTED_STRING,
    make_metadata_leak_pdf,
    make_overlay_only_pdf,
    make_properly_redacted_pdf,
    make_translucent_box_pdf,
)


def _ocr_first_page(pdf_bytes: bytes) -> str:
    """Rasterize the first page and return the raw OCR text (test-side, mirrors the gate)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pix = doc[0].get_pixmap(dpi=OCR_RASTER_DPI)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        return str(pytesseract.image_to_string(image))
    finally:
        doc.close()


def _docinfo_and_xmp(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        docinfo = " ".join(v for v in doc.metadata.values() if v)
        xmp = doc.get_xml_metadata() or ""
        return f"{docinfo} {xmp}"
    finally:
        doc.close()


def test_overlay_only_pdf_has_intact_text_layer() -> None:
    doc = fitz.open(stream=make_overlay_only_pdf(), filetype="pdf")
    try:
        assert DEFAULT_REDACTED_STRING in doc[0].get_text()
    finally:
        doc.close()


def test_metadata_leak_pdf_has_string_in_docinfo_or_xmp() -> None:
    docinfo = normalize_text(_docinfo_and_xmp(make_metadata_leak_pdf(location="docinfo")))
    xmp = normalize_text(_docinfo_and_xmp(make_metadata_leak_pdf(location="xmp")))
    target = normalize_text(DEFAULT_REDACTED_STRING)
    assert target in docinfo
    assert target in xmp


def test_metadata_leak_pdf_body_has_no_text_leak() -> None:
    # The visible body must be clean; only the metadata leaks. This keeps the
    # metadata-check test from being contaminated by a text-layer hit.
    doc = fitz.open(stream=make_metadata_leak_pdf(), filetype="pdf")
    try:
        assert DEFAULT_REDACTED_STRING not in doc[0].get_text()
    finally:
        doc.close()


def test_translucent_box_pdf_has_no_text_layer() -> None:
    doc = fitz.open(stream=make_translucent_box_pdf(), filetype="pdf")
    try:
        assert doc[0].get_text().strip() == ""
    finally:
        doc.close()


@pytest.mark.real_ocr
def test_translucent_box_pdf_rasterizes_to_legible_text() -> None:
    ocr_text = normalize_text(_ocr_first_page(make_translucent_box_pdf()))
    score = fuzz.partial_ratio(normalize_text(DEFAULT_REDACTED_STRING), ocr_text)
    assert score >= OCR_MATCH_THRESHOLD


@pytest.mark.real_ocr
def test_properly_redacted_control_pdf_has_no_text_layer_and_no_metadata_leak() -> None:
    pdf_bytes = make_properly_redacted_pdf()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        assert DEFAULT_REDACTED_STRING not in doc[0].get_text()
    finally:
        doc.close()
    assert normalize_text(DEFAULT_REDACTED_STRING) not in normalize_text(_docinfo_and_xmp(pdf_bytes))
    ocr_text = normalize_text(_ocr_first_page(pdf_bytes))
    assert fuzz.partial_ratio(normalize_text(DEFAULT_REDACTED_STRING), ocr_text) < OCR_MATCH_THRESHOLD
