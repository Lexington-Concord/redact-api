"""Detection orchestration: run Tier-1 + Tier-2 detectors over a document's pages and
persist the surviving candidate spans (redact-api#8).

Given the already-extracted ``PageModel`` list for a document (detect_job re-derives these
from the original PDF via ``ingest.pdf.extract_pages``), this runs every Tier-1 regex
detector plus the Tier-2 NER batch, dedupes Tier-2 against Tier-1 (Tier-1 wins), and
writes one ``Span`` row per surviving candidate under a get-or-create ``Page`` row. Pure
detection logic (``tier1``/``tier2``) stays in the detection package; this service owns
only the orchestration and persistence.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from redact_api.detection import tier1, tier2
from redact_api.detection.models import CandidateSpan
from redact_api.ingest.models import PageModel
from redact_api.models.page import Page
from redact_api.models.span import Span

LOGGER = logging.getLogger(__name__)

# Every Tier-1 regex detector, run in a fixed order over each page's raw text.
_TIER1_DETECTORS: tuple[Callable[[PageModel], list[CandidateSpan]], ...] = (
    tier1.detect_ssn,
    tier1.detect_phone,
    tier1.detect_email,
    tier1.detect_account_number,
    tier1.detect_license_plate,
    tier1.detect_dob,
)


async def run_detection(session: AsyncSession, document_id: UUID, pages: list[PageModel]) -> int:
    """Detect PII across ``pages`` and persist a ``Span`` row per candidate.

    Runs the Tier-2 NER batch once over all pages (its single-call batching contract),
    merges each page's Tier-1 and Tier-2 candidates, and writes the survivors under a
    get-or-create ``Page`` row. Returns the total number of spans persisted. The caller
    owns the transaction (this flushes but does not commit).
    """
    tier2_by_page = tier2.detect_entities_batch(pages)
    total_spans = 0
    for page, tier2_spans in zip(pages, tier2_by_page, strict=True):
        candidates = _detect_page(page, tier2_spans)
        if not candidates:
            continue
        db_page = await _get_or_create_page(session, document_id, page.page_number)
        for candidate in candidates:
            session.add(_candidate_to_span(db_page.id, candidate))
        total_spans += len(candidates)
    await session.flush()  # type: ignore[attr-defined]
    LOGGER.info("detection_completed", extra={"document_id": str(document_id), "span_count": total_spans})
    return total_spans


def _detect_page(page: PageModel, tier2_spans: list[CandidateSpan]) -> list[CandidateSpan]:
    """Run all Tier-1 detectors on ``page`` and dedupe the Tier-2 candidates against them."""
    tier1_spans = [span for detector in _TIER1_DETECTORS for span in detector(page)]
    return tier2.dedupe_tier2_against_tier1(page, tier1_spans, tier2_spans)


def _candidate_to_span(page_id: UUID, candidate: CandidateSpan) -> Span:
    """Map a DB-free ``CandidateSpan`` onto a persistable ``Span`` under ``page_id``."""
    return Span(
        page_id=page_id,
        bboxes=[list(bbox) for bbox in candidate.bboxes],
        text=candidate.text,
        category=candidate.category,
        source_tier=candidate.source_tier,
        confidence=candidate.confidence,
    )


async def _get_or_create_page(session: AsyncSession, document_id: UUID, page_number: int) -> Page:
    """Return the page for ``(document_id, page_number)``, creating it if absent."""
    result = await session.execute(
        select(Page).where(col(Page.document_id) == document_id).where(col(Page.page_number) == page_number)
    )
    page = result.scalar_one_or_none()
    if page is None:
        page = Page(document_id=document_id, page_number=page_number)
        session.add(page)
        await session.flush()  # type: ignore[attr-defined]
    return page
