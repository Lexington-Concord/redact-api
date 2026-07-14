"""Truth-table tests for ``detect_dob`` (detection/tier1.py).

A date only counts as a date-of-birth when a keyword anchor (``DOB``,
``Date of Birth``, ``Born``; case-insensitive) appears within the 32 raw
characters immediately preceding it. Unanchored dates -- including municipal
meeting/filing dates -- must NOT match.
"""

from __future__ import annotations

from redact_api.detection.consts import CATEGORY_DOB, CONFIDENCE_REGEX_ONLY, DOB_ANCHOR_WINDOW_CHARS
from redact_api.detection.tier1 import detect_dob
from redact_api.tests.fixtures.detection_pages import assert_candidate, make_page

# Length of the anchor keyword used in the boundary vectors below ("DOB").
_ANCHOR_LEN = 3

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
        assert_candidate(
            span, page, category=CATEGORY_DOB, confidence=CONFIDENCE_REGEX_ONLY, expected_text="01/02/1990"
        )

    def test_anchor_exactly_at_window_boundary_is_detected(self) -> None:
        # "DOB" immediately followed by filler such that "DOB"+filler is
        # exactly DOB_ANCHOR_WINDOW_CHARS long: the anchor's leading char sits
        # right at the window's left edge and must still be found (R8's window
        # is inclusive of all 32 preceding chars, not 31).
        filler = "x" * (DOB_ANCHOR_WINDOW_CHARS - _ANCHOR_LEN)
        page = make_page(f"DOB{filler}01/02/1990")
        (span,) = detect_dob(page)
        assert span.text == "01/02/1990"


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

    def test_anchor_one_char_past_window_boundary_is_not_detected(self) -> None:
        # One character more than the exact-boundary vector above: "DOB"+filler
        # is DOB_ANCHOR_WINDOW_CHARS + 1 long, so the window's left edge cuts
        # off the anchor's leading "D" -- must not match.
        filler = "x" * (DOB_ANCHOR_WINDOW_CHARS - _ANCHOR_LEN + 1)
        page = make_page(f"DOB{filler}01/02/1990")
        assert detect_dob(page) == []
