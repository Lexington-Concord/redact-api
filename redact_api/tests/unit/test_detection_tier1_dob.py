"""Truth-table tests for ``detect_dob`` (detection/tier1.py).

A date only counts as a date-of-birth when a keyword anchor (``DOB``,
``Date of Birth``, ``Born``; case-insensitive) appears within the 32 raw
characters immediately preceding it. Unanchored dates -- including municipal
meeting/filing dates -- must NOT match.
"""

from __future__ import annotations

from redact_api.detection.consts import CATEGORY_DOB, CONFIDENCE_REGEX_ONLY
from redact_api.detection.tier1 import detect_dob
from redact_api.models.span import SourceTier
from redact_api.tests.fixtures.detection_pages import make_page

# (page text, expected matched date text)
_TRUE_POSITIVES = [
    ("DOB: 01/02/1990", "01/02/1990"),
    ("Date of Birth: 1-2-90", "1-2-90"),
    ("Patient born 12/31/1985", "12/31/1985"),
    ("dob 07/04/1976 recorded", "07/04/1976"),  # case-insensitive anchor
]

_NEAR_MISSES = [
    "Report dated 01/02/1990",  # unanchored date
    "Meeting Date: 03/15/2024",  # municipal agenda date (mandatory near-miss)
    "Filed: 06/01/2023",  # filing date (mandatory near-miss)
]


class TestDetectDobTruePositives:
    def test_each_anchored_date_is_detected(self) -> None:
        for text, expected in _TRUE_POSITIVES:
            page = make_page(text)
            spans = detect_dob(page)
            assert [span.text for span in spans] == [expected], text

    def test_span_metadata(self) -> None:
        page = make_page("DOB: 01/02/1990")
        (span,) = detect_dob(page)
        assert span.category == CATEGORY_DOB
        assert span.source_tier == SourceTier.TIER_1
        assert span.confidence == CONFIDENCE_REGEX_ONLY
        assert page.text[span.start : span.end] == "01/02/1990"
        assert span.bboxes


class TestDetectDobNearMisses:
    def test_unanchored_and_municipal_dates_are_not_detected(self) -> None:
        for text in _NEAR_MISSES:
            page = make_page(text)
            assert detect_dob(page) == [], text

    def test_anchor_beyond_window_is_not_detected(self) -> None:
        # 'DOB' followed by >32 chars of filler before the date must not anchor it.
        filler = "x" * 40
        page = make_page(f"DOB {filler} 01/02/1990")
        assert detect_dob(page) == []
