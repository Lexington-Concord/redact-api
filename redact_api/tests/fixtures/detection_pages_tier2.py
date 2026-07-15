"""Tier-2 (NER) assertion helpers, layered over ``detection_pages`` builders.

Tier-1's ``assert_candidate`` hardcodes ``source_tier == TIER_1`` and exact
confidence equality -- both wrong for Presidio-backed Tier-2 spans, whose scores
are model-derived and whose tier is ``TIER_2``. Rather than touch the Tier-1
fixture (redact-api#4 file, left unchanged), this sibling module re-exports
``make_page`` unchanged and adds a Tier-2-shaped assertion helper that checks
character-range *overlap* (not equality) against an expected window and a
confidence *floor* (not an exact score), matching the loose-assertion contract
Tier-2 detection requires (R8).
"""

from __future__ import annotations

from redact_api.detection.consts import TIER2_MIN_CONFIDENCE
from redact_api.detection.models import CandidateSpan
from redact_api.ingest.models import PageModel
from redact_api.models.span import SourceTier
from redact_api.tests.fixtures.detection_pages import make_page

__all__ = ["assert_tier2_candidate", "covering_tier2_span", "make_page"]


def covering_tier2_span(
    spans: list[CandidateSpan],
    *,
    category: str,
    expected_start: int,
    expected_end: int,
) -> CandidateSpan:
    """Return the first ``spans`` entry of ``category`` overlapping the window.

    A model detector can return several spans per page and its entity
    boundaries need not equal the caller's word window, so truth-table tests
    locate the relevant span by half-open overlap (the same predicate
    ``resolve_span_bboxes`` uses) rather than assuming position or exact
    boundaries (R8). Raises ``AssertionError`` if no such span exists.
    """
    for span in spans:
        if span.category == category and span.start < expected_end and expected_start < span.end:
            return span
    message = f"no {category} span overlapping [{expected_start}, {expected_end}) in {spans}"
    raise AssertionError(message)


def assert_tier2_candidate(
    span: CandidateSpan,
    page: PageModel,
    *,
    category: str,
    expected_start: int,
    expected_end: int,
) -> None:
    """Assert a Tier-2 ``span`` covers the expected window on ``page``.

    Uses loose assertions appropriate to a model-derived detector (R8): the
    span's ``[start, end)`` must *overlap* the ``[expected_start, expected_end)``
    window via the same half-open predicate ``resolve_span_bboxes`` uses (rather
    than match it exactly, since spaCy's entity boundaries can differ from the
    caller's word window), confidence must clear the ``TIER2_MIN_CONFIDENCE``
    floor, and ``source_tier`` must be ``TIER_2`` -- which holds only for
    un-merged Tier-2 survivors (a Tier-1/Tier-2 merge keeps Tier-1's tier).
    """
    assert span.category == category
    assert span.source_tier == SourceTier.TIER_2
    # Half-open any-overlap predicate, identical to resolve_span_bboxes.
    assert span.start < expected_end
    assert expected_start < span.end
    assert span.confidence >= TIER2_MIN_CONFIDENCE
    assert page.text[span.start : span.end] == span.text
    assert span.bboxes
