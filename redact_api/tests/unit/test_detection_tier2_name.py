"""Truth-table tests for Tier-2 PERSON detection (detection/tier2.py).

Presidio's spaCy ``en_core_web_lg`` backend supplies the PERSON entities that
map to ``CATEGORY_NAME``. These exercise the real model (via ``detect_entities``
-> ``detect_entities_batch`` -> ``nlp.pipe``), asserting overlap/coverage rather
than exact spaCy boundaries (R8).
"""

from __future__ import annotations

from redact_api.detection.consts import CATEGORY_NAME
from redact_api.detection.tier2 import detect_entities
from redact_api.tests.fixtures.detection_pages_tier2 import (
    assert_tier2_candidate,
    covering_tier2_span,
    make_page,
)


class TestDetectName:
    def test_single_person_detected(self) -> None:
        text = "Dr. Jane Doe reviewed the chart."
        page = make_page(text)
        start = text.index("Jane Doe")
        end = start + len("Jane Doe")
        span = covering_tier2_span(
            detect_entities(page), category=CATEGORY_NAME, expected_start=start, expected_end=end
        )
        assert_tier2_candidate(span, page, category=CATEGORY_NAME, expected_start=start, expected_end=end)

    def test_multiple_people_detected(self) -> None:
        text = "Jane Doe met with Robert Johnson today."
        page = make_page(text)
        spans = detect_entities(page)
        for name in ("Jane Doe", "Robert Johnson"):
            start = text.index(name)
            end = start + len(name)
            span = covering_tier2_span(spans, category=CATEGORY_NAME, expected_start=start, expected_end=end)
            assert_tier2_candidate(span, page, category=CATEGORY_NAME, expected_start=start, expected_end=end)

    def test_no_person_in_neutral_text(self) -> None:
        page = make_page("The invoice total was paid in full.")
        assert [span for span in detect_entities(page) if span.category == CATEGORY_NAME] == []
