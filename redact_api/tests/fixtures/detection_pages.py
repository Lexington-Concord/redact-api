"""In-memory ``PageModel`` builders for Tier-1 detection unit tests.

These build a ``PageModel`` directly from a raw text string (no PDF machinery),
deriving one ``WordBBox`` per whitespace-delimited token with synthetic but
internally-consistent character offsets and bounding boxes. ``page.text`` is the
verbatim input, so detector regex offsets line up with ``WordBBox.start``/``end``
exactly the way they would against real ingest output.
"""

from __future__ import annotations

import re

from redact_api.ingest.models import PageModel, WordBBox

_TOKEN_RE = re.compile(r"\S+")
_PAGE_WIDTH = 612.0
_PAGE_HEIGHT = 792.0
_LINE_TOP = 100.0
_LINE_BOTTOM = 112.0


def make_page(text: str, page_number: int = 1) -> PageModel:
    """Build a single-line ``PageModel`` whose words track ``text`` char offsets.

    Each whitespace-delimited token becomes a ``WordBBox`` with a synthetic bbox
    (1 point per character horizontally, a fixed line band vertically) so
    ``resolve_span_bboxes`` has real, ordered geometry to map matches onto.
    """
    words = [
        WordBBox(
            start=match.start(),
            end=match.end(),
            bbox=(float(match.start()), _LINE_TOP, float(match.end()), _LINE_BOTTOM),
        )
        for match in _TOKEN_RE.finditer(text)
    ]
    return PageModel(
        page_number=page_number,
        width=_PAGE_WIDTH,
        height=_PAGE_HEIGHT,
        text=text,
        words=words,
        rotation=0,
        raster_key="",
    )
