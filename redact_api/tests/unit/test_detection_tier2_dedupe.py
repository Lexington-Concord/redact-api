"""Pure-function tests for ``dedupe_tier2_against_tier1`` (detection/tier2.py).

These construct ``CandidateSpan`` instances and a ``make_page``-built ``PageModel``
directly -- no Presidio/spaCy invocation (R9). On a same-page/same-category
overlap, Tier 1 wins but the survivor's char range *widens* to the union of both
detectors' ranges, its ``bboxes``/``text`` are recomputed over that range (via
``resolve_span_bboxes``, never a hand-built union rectangle), and its
``source_tier``/``confidence`` stay Tier-1's -- so a word either detector flagged
stays in coverage (R6, operator's binding merge resolution).
"""

from __future__ import annotations

from redact_api.detection.base import resolve_span_bboxes
from redact_api.detection.consts import (
    CATEGORY_NAME,
    CATEGORY_ORGANIZATION,
    CONFIDENCE_REGEX_ONLY,
    TIER2_MIN_CONFIDENCE,
)
from redact_api.detection.models import CandidateSpan
from redact_api.detection.tier2 import dedupe_tier2_against_tier1
from redact_api.ingest.models import PageModel
from redact_api.models.span import SourceTier
from redact_api.tests.fixtures.detection_pages_tier2 import make_page

# "Name John Smith Jr end" -- offsets: John[5,9) Smith[10,15) Jr[16,18) end[19,22)
_TEXT = "Name John Smith Jr end"


def _span(
    page: PageModel,
    start: int,
    end: int,
    *,
    category: str,
    tier: SourceTier,
    confidence: float,
    page_number: int | None = None,
) -> CandidateSpan:
    return CandidateSpan(
        page_number=page.page_number if page_number is None else page_number,
        start=start,
        end=end,
        bboxes=resolve_span_bboxes(page, start, end),
        text=page.text[start:end],
        category=category,
        source_tier=tier,
        confidence=confidence,
    )


class TestNoOverlap:
    def test_both_pass_through_unchanged(self) -> None:
        page = make_page(_TEXT)
        t1 = _span(page, 5, 9, category=CATEGORY_NAME, tier=SourceTier.TIER_1, confidence=CONFIDENCE_REGEX_ONLY)
        t2 = _span(page, 19, 22, category=CATEGORY_NAME, tier=SourceTier.TIER_2, confidence=TIER2_MIN_CONFIDENCE)

        result = dedupe_tier2_against_tier1(page, [t1], [t2])

        assert t1 in result
        assert t2 in result
        assert len(result) == 2


class TestContainedOverlapIsNoOp:
    def test_survivor_keeps_tier1_range_and_metadata(self) -> None:
        page = make_page(_TEXT)
        t1 = _span(page, 5, 18, category=CATEGORY_NAME, tier=SourceTier.TIER_1, confidence=CONFIDENCE_REGEX_ONLY)
        t2 = _span(page, 10, 15, category=CATEGORY_NAME, tier=SourceTier.TIER_2, confidence=TIER2_MIN_CONFIDENCE)

        result = dedupe_tier2_against_tier1(page, [t1], [t2])

        assert len(result) == 1
        (survivor,) = result
        assert survivor.start == 5
        assert survivor.end == 18
        assert survivor.bboxes == t1.bboxes
        assert survivor.source_tier == SourceTier.TIER_1
        assert survivor.confidence == CONFIDENCE_REGEX_ONLY


class TestDifferentCategory:
    def test_no_merge_both_kept(self) -> None:
        page = make_page(_TEXT)
        t1 = _span(page, 5, 15, category=CATEGORY_NAME, tier=SourceTier.TIER_1, confidence=CONFIDENCE_REGEX_ONLY)
        t2 = _span(
            page, 5, 15, category=CATEGORY_ORGANIZATION, tier=SourceTier.TIER_2, confidence=TIER2_MIN_CONFIDENCE
        )

        result = dedupe_tier2_against_tier1(page, [t1], [t2])

        assert len(result) == 2
        assert t1 in result
        assert t2 in result


class TestDifferentPage:
    def test_page_guard_blocks_merge(self) -> None:
        page = make_page(_TEXT)
        t1 = _span(page, 5, 15, category=CATEGORY_NAME, tier=SourceTier.TIER_1, confidence=CONFIDENCE_REGEX_ONLY)
        t2 = _span(
            page,
            5,
            15,
            category=CATEGORY_NAME,
            tier=SourceTier.TIER_2,
            confidence=TIER2_MIN_CONFIDENCE,
            page_number=2,
        )

        result = dedupe_tier2_against_tier1(page, [t1], [t2])

        assert len(result) == 2
        assert t1 in result
        assert t2 in result


class TestBoundaryExtensionMerge:
    def test_ner_span_extends_one_word_past_regex_match(self) -> None:
        page = make_page(_TEXT)
        # Tier-1 regex matched "John Smith"; NER extends to "John Smith Jr".
        t1 = _span(page, 5, 15, category=CATEGORY_NAME, tier=SourceTier.TIER_1, confidence=CONFIDENCE_REGEX_ONLY)
        t2 = _span(page, 5, 18, category=CATEGORY_NAME, tier=SourceTier.TIER_2, confidence=TIER2_MIN_CONFIDENCE)

        result = dedupe_tier2_against_tier1(page, [t1], [t2])

        assert len(result) == 1
        (survivor,) = result
        # (a) surviving end equals the Tier-2 end, strictly past the Tier-1 end.
        assert survivor.end == 18
        assert survivor.end > t1.end
        assert survivor.start == 5
        # (b) bboxes now include the extra word "Jr" (recomputed, not hand-unioned).
        jr_bbox = next(word.bbox for word in page.words if page.text[word.start : word.end] == "Jr")
        assert jr_bbox in survivor.bboxes
        assert survivor.bboxes == resolve_span_bboxes(page, 5, 18)
        # (c) text is recomputed over the merged range.
        assert survivor.text == page.text[5:18]
        assert survivor.text == "John Smith Jr"
        # (d) Tier-1's provenance/confidence are unchanged by the merge.
        assert survivor.source_tier == SourceTier.TIER_1
        assert survivor.confidence == CONFIDENCE_REGEX_ONLY
