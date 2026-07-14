"""Truth-table tests for ``detect_account_number`` (detection/tier1.py).

Scope is Luhn-only: an unbroken digit run of an accepted length that passes the
Luhn checksum. Near-misses are same-length Luhn-failing runs plus runs that are
too short or too long to be considered.
"""

from __future__ import annotations

from redact_api.detection.consts import CATEGORY_ACCOUNT_NUMBER, CONFIDENCE_VALIDATED
from redact_api.detection.tier1 import detect_account_number
from redact_api.models.span import SourceTier
from redact_api.tests.fixtures.detection_pages import make_page

_TRUE_POSITIVES = [
    "123456789015",  # 12 digits, Luhn-valid (lower length bound)
    "4242424242424242",  # 16 digits, Luhn-valid
    "4000000000000000006",  # 19 digits, Luhn-valid (upper length bound)
]

_NEAR_MISSES = [
    "4242424242424241",  # 16 digits, same length, Luhn-invalid
    "12345678901",  # 11 digits, too short
    "42424242424242424242",  # 20 digits, too long
]


class TestDetectAccountNumberTruePositives:
    def test_each_valid_account_number_is_detected_once(self) -> None:
        for number in _TRUE_POSITIVES:
            page = make_page(f"Account {number} active")
            spans = detect_account_number(page)
            assert [span.text for span in spans] == [number], number

    def test_span_metadata(self) -> None:
        page = make_page("Account 4242424242424242 active")
        (span,) = detect_account_number(page)
        assert span.category == CATEGORY_ACCOUNT_NUMBER
        assert span.source_tier == SourceTier.TIER_1
        assert span.confidence == CONFIDENCE_VALIDATED
        assert page.text[span.start : span.end] == "4242424242424242"
        assert span.bboxes


class TestDetectAccountNumberNearMisses:
    def test_near_misses_are_not_detected(self) -> None:
        for candidate in _NEAR_MISSES:
            page = make_page(f"ref {candidate} noted")
            assert detect_account_number(page) == [], candidate
