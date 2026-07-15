"""Truth-table tests for Tier-2 LOCATION detection (detection/tier2.py).

Presidio maps spaCy's ``GPE``/``LOC``/``FAC`` labels onto the ``LOCATION`` entity,
which ``tier2.py`` maps to ``CATEGORY_LOCATION``. Asserts overlap/coverage, not
exact spaCy boundaries (R8).
"""

from __future__ import annotations

from redact_api.detection.consts import CATEGORY_LOCATION
from redact_api.detection.tier2 import detect_entities
from redact_api.tests.fixtures.detection_pages_tier2 import (
    assert_tier2_candidate,
    covering_tier2_span,
    make_page,
)


class TestDetectLocation:
    def test_city_detected(self) -> None:
        text = "The office relocated to Seattle last spring."
        page = make_page(text)
        start = text.index("Seattle")
        end = start + len("Seattle")
        span = covering_tier2_span(
            detect_entities(page), category=CATEGORY_LOCATION, expected_start=start, expected_end=end
        )
        assert_tier2_candidate(span, page, category=CATEGORY_LOCATION, expected_start=start, expected_end=end)

    def test_multiple_locations_detected(self) -> None:
        text = "She flew from New York to California overnight."
        page = make_page(text)
        spans = detect_entities(page)
        for place in ("New York", "California"):
            start = text.index(place)
            end = start + len(place)
            span = covering_tier2_span(spans, category=CATEGORY_LOCATION, expected_start=start, expected_end=end)
            assert_tier2_candidate(span, page, category=CATEGORY_LOCATION, expected_start=start, expected_end=end)

    def test_no_location_in_neutral_text(self) -> None:
        page = make_page("The invoice total was paid in full.")
        assert [span for span in detect_entities(page) if span.category == CATEGORY_LOCATION] == []
