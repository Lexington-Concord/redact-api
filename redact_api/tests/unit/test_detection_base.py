"""Tests for ``resolve_span_bboxes`` (detection/base.py).

Unit tests -- no database, no PDF machinery. Pages are built with explicit
``WordBBox`` geometry so the any-overlap predicate can be checked at each
boundary condition.
"""

from __future__ import annotations

from redact_api.detection.base import resolve_span_bboxes
from redact_api.ingest.models import PageModel, WordBBox

_LINE_TOP = 100.0
_LINE_BOTTOM = 112.0


def _page(words: list[WordBBox], text: str = "") -> PageModel:
    return PageModel(
        page_number=1,
        width=612.0,
        height=792.0,
        text=text,
        words=words,
        rotation=0,
        raster_key="",
    )


def _word(start: int, end: int) -> WordBBox:
    return WordBBox(start=start, end=end, bbox=(float(start), _LINE_TOP, float(end), _LINE_BOTTOM))


class TestResolveSpanBboxes:
    def test_exact_match_single_word(self) -> None:
        word = _word(0, 5)
        page = _page([word])
        assert resolve_span_bboxes(page, 0, 5) == [word.bbox]

    def test_multi_word_span_returns_one_bbox_per_word_in_order(self) -> None:
        first = _word(0, 3)
        second = _word(4, 7)
        page = _page([first, second])
        assert resolve_span_bboxes(page, 0, 7) == [first.bbox, second.bbox]

    def test_partial_overlap_at_start_boundary(self) -> None:
        word = _word(5, 10)
        page = _page([word])
        # Span (3, 7) overlaps the word only on its leading edge.
        assert resolve_span_bboxes(page, 3, 7) == [word.bbox]

    def test_partial_overlap_at_end_boundary(self) -> None:
        word = _word(5, 10)
        page = _page([word])
        # Span (8, 15) overlaps the word only on its trailing edge.
        assert resolve_span_bboxes(page, 8, 15) == [word.bbox]

    def test_no_overlap_returns_empty(self) -> None:
        word = _word(0, 5)
        page = _page([word])
        assert resolve_span_bboxes(page, 10, 15) == []

    def test_zero_length_match_at_boundary_returns_empty(self) -> None:
        # A zero-length span abutting word boundaries touches nothing under the
        # half-open any-overlap predicate.
        page = _page([_word(0, 5), _word(5, 10)])
        assert resolve_span_bboxes(page, 5, 5) == []

    def test_only_contributing_words_are_returned(self) -> None:
        first = _word(0, 3)
        middle = _word(4, 7)
        last = _word(8, 11)
        page = _page([first, middle, last])
        # Span (5, 6) sits wholly inside the middle word.
        assert resolve_span_bboxes(page, 5, 6) == [middle.bbox]

    def test_never_returns_a_single_union_rect(self) -> None:
        first = _word(0, 3)
        second = _word(4, 7)
        page = _page([first, second])
        result = resolve_span_bboxes(page, 0, 7)
        assert len(result) == 2
