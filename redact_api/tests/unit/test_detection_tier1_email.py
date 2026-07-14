"""Truth-table tests for ``detect_email`` (detection/tier1.py).

Candidates are pulled from raw text by a coarse regex, then confirmed with
``email_validator.validate_email`` -- so near-misses include both regex
non-matches and strings that match the regex but fail RFC validation.
"""

from __future__ import annotations

from redact_api.detection.consts import CATEGORY_EMAIL, CONFIDENCE_REGEX_ONLY
from redact_api.detection.tier1 import detect_email
from redact_api.models.span import SourceTier
from redact_api.tests.fixtures.detection_pages import make_page

_TRUE_POSITIVES = [
    "jane.doe@example.com",
    "jane+tag@example.com",
    "jane@mail.sub.example.com",
]

_NEAR_MISSES = [
    "plainaddress",  # missing @
    "user@example",  # missing TLD
    "user@@example.com",  # double @
    "user@-example.com",  # regex-pass, validator-reject (hyphen-leading domain)
    "john.doe@company,com",  # punctuation breaks the domain
]


class TestDetectEmailTruePositives:
    def test_each_valid_email_is_detected_once(self) -> None:
        for email in _TRUE_POSITIVES:
            page = make_page(f"Reach me at {email} anytime")
            spans = detect_email(page)
            assert [span.text for span in spans] == [email], email

    def test_trailing_sentence_punctuation_is_excluded_from_match(self) -> None:
        page = make_page("Reach me at jane@example.com, please")
        (span,) = detect_email(page)
        assert span.text == "jane@example.com"

    def test_span_metadata(self) -> None:
        page = make_page("Reach me at jane.doe@example.com anytime")
        (span,) = detect_email(page)
        assert span.category == CATEGORY_EMAIL
        assert span.source_tier == SourceTier.TIER_1
        assert span.confidence == CONFIDENCE_REGEX_ONLY
        assert page.text[span.start : span.end] == "jane.doe@example.com"
        assert span.bboxes


class TestDetectEmailNearMisses:
    def test_near_misses_are_not_detected(self) -> None:
        for candidate in _NEAR_MISSES:
            page = make_page(f"contact {candidate} listed")
            assert detect_email(page) == [], candidate
