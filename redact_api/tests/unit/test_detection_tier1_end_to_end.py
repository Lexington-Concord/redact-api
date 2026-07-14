"""End-to-end Tier-1 detection over real ``extract_pages`` output.

Unlike the per-category truth tables (which build ``PageModel`` in memory), this
file drives the detectors against a real PyMuPDF-extracted page so the whole
path -- text reconstruction, ``WordBBox`` offsets, and ``resolve_span_bboxes``
geometry -- is exercised together.
"""

from __future__ import annotations

from redact_api.detection.consts import (
    CATEGORY_ACCOUNT_NUMBER,
    CATEGORY_DOB,
    CATEGORY_EMAIL,
    CATEGORY_LICENSE_PLATE,
    CATEGORY_PHONE,
    CATEGORY_SSN,
)
from redact_api.detection.models import CandidateSpan
from redact_api.detection.tier1 import (
    detect_account_number,
    detect_dob,
    detect_email,
    detect_license_plate,
    detect_phone,
    detect_ssn,
)
from redact_api.ingest.models import PageModel
from redact_api.ingest.pdf import extract_pages
from redact_api.models.span import SourceTier
from redact_api.tests.fixtures.ingest_pdfs import build_pii_sample_pdf


def _sample_page() -> PageModel:
    extractions = extract_pages(build_pii_sample_pdf())
    assert len(extractions) == 1
    return extractions[0].page


def _assert_bboxes_are_real(span: CandidateSpan, page: PageModel) -> None:
    assert span.bboxes, span
    page_bboxes = {word.bbox for word in page.words}
    for bbox in span.bboxes:
        assert bbox in page_bboxes, bbox


class TestTier1EndToEnd:
    def test_ssn_detected(self) -> None:
        page = _sample_page()
        (span,) = detect_ssn(page)
        assert span.text == "123-45-6789"
        assert span.category == CATEGORY_SSN
        assert span.source_tier == SourceTier.TIER_1
        assert page.text[span.start : span.end] == span.text
        _assert_bboxes_are_real(span, page)

    def test_phone_detected(self) -> None:
        page = _sample_page()
        (span,) = detect_phone(page)
        assert span.text == "212-555-0142"
        assert span.category == CATEGORY_PHONE
        assert page.text[span.start : span.end] == span.text
        _assert_bboxes_are_real(span, page)

    def test_email_detected(self) -> None:
        page = _sample_page()
        (span,) = detect_email(page)
        assert span.text == "jane.doe@example.com"
        assert span.category == CATEGORY_EMAIL
        assert page.text[span.start : span.end] == span.text
        _assert_bboxes_are_real(span, page)

    def test_account_number_detected(self) -> None:
        page = _sample_page()
        (span,) = detect_account_number(page)
        assert span.text == "4242424242424242"
        assert span.category == CATEGORY_ACCOUNT_NUMBER
        assert page.text[span.start : span.end] == span.text
        _assert_bboxes_are_real(span, page)

    def test_license_plate_detected(self) -> None:
        page = _sample_page()
        spans = detect_license_plate(page)
        plate_texts = [span.text for span in spans]
        assert "ABC1234" in plate_texts
        plate = next(span for span in spans if span.text == "ABC1234")
        assert plate.category == CATEGORY_LICENSE_PLATE
        _assert_bboxes_are_real(plate, page)

    def test_dob_detected(self) -> None:
        page = _sample_page()
        (span,) = detect_dob(page)
        assert span.text == "01/02/1990"
        assert span.category == CATEGORY_DOB
        assert page.text[span.start : span.end] == span.text
        _assert_bboxes_are_real(span, page)
