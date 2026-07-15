"""Integration tests for the detection-service persistence orchestration (redact-api#8).

Exercises ``run_detection`` against a real database. Tier-2 NER is stubbed to empty here so
these tests stay fast and deterministic -- Tier-2 accuracy is covered by the detection unit
tests, and a real Tier-1+Tier-2 pass through the task is covered by test_tasks_detect_job.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.ingest.pdf import extract_pages
from redact_api.models.document import Document
from redact_api.models.organization import Organization
from redact_api.models.page import Page
from redact_api.models.span import Span
from redact_api.services.detection_service import run_detection
from redact_api.tests.fixtures.ingest_pdfs import build_multi_page_pdf, build_pii_sample_pdf


@pytest.fixture(autouse=True)
def _stub_tier2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub Tier-2 NER to no candidates so these tests exercise only Tier-1 + persistence."""
    monkeypatch.setattr(
        "redact_api.detection.tier2.detect_entities_batch",
        lambda pages: [[] for _ in pages],
    )


async def _pages_from(pdf_bytes: bytes) -> list:
    return [extraction.page for extraction in extract_pages(pdf_bytes)]


class TestRunDetection:
    async def test_persists_tier1_spans(
        self,
        session: AsyncSession,
        make_organization: Callable[[], Awaitable[Organization]],
        make_document: Callable[..., Awaitable[Document]],
    ) -> None:
        org = await make_organization()
        document = await make_document(org.id)
        pages = await _pages_from(build_pii_sample_pdf())

        count = await run_detection(session, document.id, pages)

        assert count > 0
        span_rows = (
            (
                await session.execute(
                    select(Span).join(Page, Span.page_id == Page.id).where(Page.document_id == document.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(span_rows) == count
        categories = {span.category for span in span_rows}
        # build_pii_sample_pdf embeds an SSN, which the Tier-1 detector validates and persists.
        assert "ssn" in categories

    async def test_no_spans_for_pii_free_document(
        self,
        session: AsyncSession,
        make_organization: Callable[[], Awaitable[Organization]],
        make_document: Callable[..., Awaitable[Document]],
    ) -> None:
        org = await make_organization()
        document = await make_document(org.id)
        pages = await _pages_from(build_multi_page_pdf(page_count=1))

        count = await run_detection(session, document.id, pages)

        assert count == 0
        page_count = (
            await session.execute(select(func.count()).select_from(Page).where(Page.document_id == document.id))
        ).scalar_one()
        # A page with no candidates never gets a Page row created.
        assert page_count == 0

    async def test_creates_one_page_row_per_page_with_spans(
        self,
        session: AsyncSession,
        make_organization: Callable[[], Awaitable[Organization]],
        make_document: Callable[..., Awaitable[Document]],
    ) -> None:
        org = await make_organization()
        document = await make_document(org.id)
        pages = await _pages_from(build_pii_sample_pdf())

        await run_detection(session, document.id, pages)

        page_count = (
            await session.execute(select(func.count()).select_from(Page).where(Page.document_id == document.id))
        ).scalar_one()
        assert page_count == 1
