"""Truth-table tests for Tier-2 ORGANIZATION detection (detection/tier2.py).

These double as a regression guard on the custom ``nlp_configuration``: Presidio's
shipped ``default.yaml`` lists ``ORGANIZATION`` in ``labels_to_ignore``, so a bare
``AnalyzerEngine()`` silently drops every org. ``tier2.py`` overrides that with
``labels_to_ignore: []``; if the override regresses, these tests fail (R1/R5).
"""

from __future__ import annotations

from redact_api.detection.consts import CATEGORY_ORGANIZATION
from redact_api.detection.tier2 import detect_entities
from redact_api.tests.fixtures.detection_pages_tier2 import (
    assert_tier2_candidate,
    covering_tier2_span,
    make_page,
)


class TestDetectOrganization:
    def test_company_detected(self) -> None:
        text = "Acme Corporation reported quarterly earnings."
        page = make_page(text)
        start = text.index("Acme Corporation")
        end = start + len("Acme Corporation")
        span = covering_tier2_span(
            detect_entities(page), category=CATEGORY_ORGANIZATION, expected_start=start, expected_end=end
        )
        assert_tier2_candidate(span, page, category=CATEGORY_ORGANIZATION, expected_start=start, expected_end=end)

    def test_organization_not_dropped_by_labels_to_ignore(self) -> None:
        # Regression guard: with Presidio's default labels_to_ignore this list
        # would be empty because ORGANIZATION is ignored by default.yaml.
        text = "The patient visited Massachusetts General Hospital."
        page = make_page(text)
        org_spans = [span for span in detect_entities(page) if span.category == CATEGORY_ORGANIZATION]
        assert org_spans, "ORGANIZATION was dropped -- labels_to_ignore override regressed"

    def test_no_org_in_neutral_text(self) -> None:
        page = make_page("The total was paid in full yesterday.")
        assert [span for span in detect_entities(page) if span.category == CATEGORY_ORGANIZATION] == []
