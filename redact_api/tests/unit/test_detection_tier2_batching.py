"""Batch-detection tests for Tier-2 (detection/tier2.py).

``detect_entities_batch`` is the sole spaCy entrypoint (via
``BatchAnalyzerEngine``/``nlp.pipe``) and returns one result list per input page
in input order; ``detect_entities`` is a thin single-page wrapper over it (R9).
"""

from __future__ import annotations

from redact_api.detection.consts import CATEGORY_NAME
from redact_api.detection.tier2 import detect_entities, detect_entities_batch
from redact_api.tests.fixtures.detection_pages_tier2 import make_page


class TestDetectEntitiesBatch:
    def test_result_order_matches_input_page_order(self) -> None:
        pages = [
            make_page("Alice Anderson signed the form.", page_number=1),
            make_page("The total was paid in full.", page_number=2),
            make_page("Bob Brown flew to Chicago.", page_number=3),
        ]

        results = detect_entities_batch(pages)

        assert len(results) == len(pages)
        # Page 1 carries a person, page 2 none, page 3 a person -- in that order.
        assert any(span.category == CATEGORY_NAME and "Alice" in span.text for span in results[0])
        assert all(span.category != CATEGORY_NAME for span in results[1])
        assert any(span.category == CATEGORY_NAME and "Bob" in span.text for span in results[2])

    def test_every_span_page_number_matches_its_page(self) -> None:
        pages = [
            make_page("Alice Anderson signed the form.", page_number=7),
            make_page("Bob Brown flew to Chicago.", page_number=9),
        ]

        results = detect_entities_batch(pages)

        for page, spans in zip(pages, results, strict=True):
            for span in spans:
                assert span.page_number == page.page_number

    def test_empty_input_returns_empty_list(self) -> None:
        assert detect_entities_batch([]) == []

    def test_detect_entities_matches_single_page_batch(self) -> None:
        page = make_page("Alice Anderson signed the form.")

        assert detect_entities(page) == detect_entities_batch([page])[0]
