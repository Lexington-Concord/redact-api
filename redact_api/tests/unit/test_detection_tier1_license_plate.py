"""Truth-table tests for ``detect_license_plate`` (detection/tier1.py).

Scope is a conservative generic pattern: a 5-8 char uppercase alphanumeric token
that contains BOTH at least one letter and at least one digit. Near-misses are
all-letters, all-digits, and too-short tokens.
"""

from __future__ import annotations

from redact_api.detection.consts import CATEGORY_LICENSE_PLATE, CONFIDENCE_REGEX_ONLY
from redact_api.detection.tier1 import detect_license_plate
from redact_api.models.span import SourceTier
from redact_api.tests.fixtures.detection_pages import make_page

_TRUE_POSITIVES = [
    "ABC1234",
    "7ABC123",
    "AB12345",
]

_NEAR_MISSES = [
    "ABCDEFG",  # all letters
    "1234567",  # all digits
    "AB1",  # too short
]


class TestDetectLicensePlateTruePositives:
    def test_each_valid_plate_is_detected_once(self) -> None:
        for plate in _TRUE_POSITIVES:
            page = make_page(f"Plate {plate} seen")
            spans = detect_license_plate(page)
            assert [span.text for span in spans] == [plate], plate

    def test_span_metadata(self) -> None:
        page = make_page("Plate ABC1234 seen")
        (span,) = detect_license_plate(page)
        assert span.category == CATEGORY_LICENSE_PLATE
        assert span.source_tier == SourceTier.TIER_1
        assert span.confidence == CONFIDENCE_REGEX_ONLY
        assert page.text[span.start : span.end] == "ABC1234"
        assert span.bboxes


class TestDetectLicensePlateNearMisses:
    def test_near_misses_are_not_detected(self) -> None:
        for candidate in _NEAR_MISSES:
            page = make_page(f"token {candidate} noted")
            assert detect_license_plate(page) == [], candidate
