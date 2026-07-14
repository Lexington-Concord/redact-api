"""Truth-table tests for ``detect_ssn`` (detection/tier1.py).

True positives are validly-structured dashed SSNs (SSA area/group/serial range
rules); near-misses are structurally-similar strings the SSA rules reject.
"""

from __future__ import annotations

from redact_api.detection.consts import CATEGORY_SSN, CONFIDENCE_VALIDATED
from redact_api.detection.tier1 import detect_ssn
from redact_api.tests.fixtures.detection_pages import assert_candidate, make_page

_TRUE_POSITIVES = [
    "123-45-6789",
    "001-01-0001",
    "899-65-4321",
]

_NEAR_MISSES = [
    "000-12-3456",  # area 000
    "666-12-3456",  # area 666
    "900-12-3456",  # area 900 (900-999 excluded)
    "999-12-3456",  # area 999
    "123-00-4567",  # group 00
    "123-45-0000",  # serial 0000
    "12-345-6789",  # wrong grouping
    "1234-56-7890",  # too many digits in area
    "123-45-67890",  # too many digits in serial
    "12-45-6789",  # too few digits in area
]


class TestDetectSsnTruePositives:
    def test_each_valid_ssn_is_detected_once(self) -> None:
        for ssn in _TRUE_POSITIVES:
            page = make_page(f"SSN {ssn} on file")
            spans = detect_ssn(page)
            assert [span.text for span in spans] == [ssn], ssn

    def test_span_metadata(self) -> None:
        page = make_page("SSN 123-45-6789 on file")
        (span,) = detect_ssn(page)
        assert span.page_number == 1
        assert_candidate(
            span, page, category=CATEGORY_SSN, confidence=CONFIDENCE_VALIDATED, expected_text="123-45-6789"
        )


class TestDetectSsnNearMisses:
    def test_near_misses_are_not_detected(self) -> None:
        for candidate in _NEAR_MISSES:
            page = make_page(f"value {candidate} here")
            assert detect_ssn(page) == [], candidate
