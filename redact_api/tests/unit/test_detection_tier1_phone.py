"""Truth-table tests for ``detect_phone`` (detection/tier1.py).

Scope is NANP (North American Numbering Plan): a valid area code and exchange
each begin 2-9, with an optional country-code prefix. True positives cover the
common written formats; near-misses are structurally-similar non-NANP strings.
"""

from __future__ import annotations

from redact_api.detection.consts import CATEGORY_PHONE, CONFIDENCE_REGEX_ONLY
from redact_api.detection.tier1 import detect_phone
from redact_api.models.span import SourceTier
from redact_api.tests.fixtures.detection_pages import make_page

_TRUE_POSITIVES = [
    "(212) 555-0142",
    "212-555-0142",
    "212.555.0142",
    "2125550142",
    "+1 212-555-0142",
    "1-212-555-0142",
]

_NEAR_MISSES = [
    "555-0142",  # 7-digit local only, no area code
    "112-555-0142",  # area code leading digit 1
    "012-555-0142",  # area code leading digit 0
    "212-155-0142",  # exchange leading digit 1
    "212-555-01423",  # too many trailing digits
]


class TestDetectPhoneTruePositives:
    def test_each_valid_phone_is_detected_once(self) -> None:
        for phone in _TRUE_POSITIVES:
            page = make_page(f"Call {phone} today")
            spans = detect_phone(page)
            assert [span.text for span in spans] == [phone], phone

    def test_span_metadata(self) -> None:
        page = make_page("Call 212-555-0142 today")
        (span,) = detect_phone(page)
        assert span.category == CATEGORY_PHONE
        assert span.source_tier == SourceTier.TIER_1
        assert span.confidence == CONFIDENCE_REGEX_ONLY
        assert page.text[span.start : span.end] == "212-555-0142"
        assert span.bboxes

    def test_multi_word_phone_resolves_multiple_bboxes(self) -> None:
        page = make_page("Call (212) 555-0142 today")
        (span,) = detect_phone(page)
        # "(212)" and "555-0142" are separate words, so the span spans two bboxes.
        assert len(span.bboxes) == 2


class TestDetectPhoneNearMisses:
    def test_near_misses_are_not_detected(self) -> None:
        for candidate in _NEAR_MISSES:
            page = make_page(f"number {candidate} listed")
            assert detect_phone(page) == [], candidate
