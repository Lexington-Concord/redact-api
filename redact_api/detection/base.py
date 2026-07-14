"""Shared detection helpers: mapping a text-match span back to word bboxes.

Tier-1 detectors match over the raw ``PageModel.text`` and get back character
offsets. ``resolve_span_bboxes`` turns those offsets into the bounding boxes a
redactor needs, by collecting every word whose character range overlaps the
match -- one bbox per contributing word, in document order, never a single
merged union rectangle (redact-api#4 R6).
"""

from __future__ import annotations

from redact_api.ingest.models import PageModel


def resolve_span_bboxes(page: PageModel, start: int, end: int) -> list[tuple[float, float, float, float]]:
    """Return the bbox of every word on ``page`` overlapping the ``[start, end)`` span.

    Overlap uses the half-open any-overlap predicate ``word.start < end and
    start < word.end``: a word contributes if its character range intersects the
    match at all, including partial overlaps at either boundary. A zero-length
    span (``start == end``) touches nothing. Results preserve ``page.words``
    document order, one bbox per contributing word.
    """
    return [word.bbox for word in page.words if word.start < end and start < word.end]
