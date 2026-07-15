"""Entity-mapping tests for Tier-2 detection (detection/tier2.py).

Presidio can emit entity types beyond the taxonomy this service redacts. Only the
six in ``PRESIDIO_ENTITY_TO_CATEGORY`` become ``CandidateSpan``s; everything else
is dropped. The PHONE/EMAIL/SSN entries deliberately overlap Tier-1 categories so
NER-found instances of those still land under the same category label (R5).

The mapping and drop behaviour are asserted deterministically against the pure
``_to_candidate`` builder (constructing ``RecognizerResult``s directly, no spaCy),
which keeps them independent of model-scoring drift (R8); one live case confirms
the ``entities=`` filter only lets mapped types through.
"""

from __future__ import annotations

import pytest
from presidio_analyzer import RecognizerResult

from redact_api.detection.consts import (
    CATEGORY_EMAIL,
    CATEGORY_LOCATION,
    CATEGORY_NAME,
    CATEGORY_ORGANIZATION,
    CATEGORY_PHONE,
    CATEGORY_SSN,
    PRESIDIO_ENTITY_TO_CATEGORY,
)
from redact_api.detection.tier2 import _to_candidate, detect_entities
from redact_api.tests.fixtures.detection_pages_tier2 import make_page

_ABOVE_FLOOR = 0.85


class TestEntityMappingTable:
    def test_mapping_covers_the_six_supported_entities(self) -> None:
        assert PRESIDIO_ENTITY_TO_CATEGORY == {
            "PERSON": CATEGORY_NAME,
            "ORGANIZATION": CATEGORY_ORGANIZATION,
            "LOCATION": CATEGORY_LOCATION,
            "PHONE_NUMBER": CATEGORY_PHONE,
            "EMAIL_ADDRESS": CATEGORY_EMAIL,
            "US_SSN": CATEGORY_SSN,
        }


class TestToCandidateMapping:
    @pytest.mark.parametrize(
        ("entity_type", "category"),
        [
            ("US_SSN", CATEGORY_SSN),
            ("PHONE_NUMBER", CATEGORY_PHONE),
            ("EMAIL_ADDRESS", CATEGORY_EMAIL),
        ],
    )
    def test_overlapping_tier1_entities_map_onto_tier1_categories(self, entity_type: str, category: str) -> None:
        text = "value 123-45-6789 here"
        page = make_page(text)
        start, end = text.index("123-45-6789"), text.index("123-45-6789") + len("123-45-6789")
        result = RecognizerResult(entity_type=entity_type, start=start, end=end, score=_ABOVE_FLOOR)

        candidate = _to_candidate(page, result)

        assert candidate is not None
        assert candidate.category == category
        assert candidate.text == text[start:end]

    @pytest.mark.parametrize("entity_type", ["CREDIT_CARD", "DATE_TIME", "IP_ADDRESS", "URL"])
    def test_unmapped_entity_types_are_dropped(self, entity_type: str) -> None:
        page = make_page("charged 4095260993934932 on file")
        result = RecognizerResult(entity_type=entity_type, start=0, end=7, score=_ABOVE_FLOOR)

        assert _to_candidate(page, result) is None


class TestEntityMappingLive:
    def test_only_mapped_categories_are_emitted(self) -> None:
        # Date + credit-card-shaped digits sit alongside a real email/phone; the
        # entities= filter must keep the output within the known category set.
        page = make_page("On January 5, 2020 email a@acme.org or call 415-555-0199 about card 4095260993934932.")
        spans = detect_entities(page)
        emitted = {span.category for span in spans}
        assert emitted <= set(PRESIDIO_ENTITY_TO_CATEGORY.values())
        assert CATEGORY_EMAIL in emitted
        assert CATEGORY_PHONE in emitted
