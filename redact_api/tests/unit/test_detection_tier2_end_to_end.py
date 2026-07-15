"""End-to-end Tier-2 detection over real ``extract_pages`` output.

Mirrors ``test_detection_tier1_end_to_end``: instead of an in-memory
``make_page``, this drives Presidio's NER over a real PyMuPDF-extracted page, so
the whole path -- text reconstruction, ``WordBBox`` offsets, ``nlp.pipe`` batching
(R9), and ``resolve_span_bboxes`` geometry -- is exercised together. The sample
PDF is built here (not in the #4 ingest fixture module, which is left untouched)
because Tier-2 needs person/organization/location text Tier-1 fixtures lack.
"""

from __future__ import annotations

import fitz

from redact_api.detection.consts import CATEGORY_LOCATION, CATEGORY_NAME, CATEGORY_ORGANIZATION
from redact_api.detection.models import CandidateSpan
from redact_api.detection.tier2 import detect_entities
from redact_api.ingest.models import PageModel
from redact_api.ingest.pdf import extract_pages
from redact_api.tests.fixtures.detection_pages_tier2 import assert_tier2_candidate, covering_tier2_span

_PAGE_WIDTH = 612.0
_PAGE_HEIGHT = 792.0
_LINES = [
    "Jane Doe reviewed the file.",
    "She works at Acme Corporation.",
    "The clinic is located in Seattle.",
]


def _build_ner_sample_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    y = 72.0
    for line in _LINES:
        page.insert_text((72, y), line, fontsize=12)
        y += 28.0
    data: bytes = doc.tobytes()
    doc.close()
    return data


def _sample_page() -> PageModel:
    extractions = extract_pages(_build_ner_sample_pdf())
    assert len(extractions) == 1
    return extractions[0].page


def _assert_covers(page: PageModel, spans: list[CandidateSpan], *, category: str, phrase: str) -> None:
    start = page.text.index(phrase)
    end = start + len(phrase)
    span = covering_tier2_span(spans, category=category, expected_start=start, expected_end=end)
    assert_tier2_candidate(span, page, category=category, expected_start=start, expected_end=end)
    page_bboxes = {word.bbox for word in page.words}
    for bbox in span.bboxes:
        assert bbox in page_bboxes, bbox


class TestTier2EndToEnd:
    def test_person_detected(self) -> None:
        page = _sample_page()
        _assert_covers(page, detect_entities(page), category=CATEGORY_NAME, phrase="Jane Doe")

    def test_organization_detected(self) -> None:
        page = _sample_page()
        _assert_covers(page, detect_entities(page), category=CATEGORY_ORGANIZATION, phrase="Acme Corporation")

    def test_location_detected(self) -> None:
        page = _sample_page()
        _assert_covers(page, detect_entities(page), category=CATEGORY_LOCATION, phrase="Seattle")
