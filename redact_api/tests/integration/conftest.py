"""Shared entity-factory fixtures for the redaction-pipeline integration tests.

Provides factory-as-fixture callables (each closes over the ``session`` fixture and
returns an async callable) so tests share entity-construction logic while still passing
call-time arguments (organization id, page number, custom ``source_tier``, etc.).
Consolidates the near-duplicate ``_make_*`` helpers previously authored independently
in ``test_redaction_models.py`` and ``test_redaction_job_service.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.models.document import Document
from redact_api.models.organization import Organization
from redact_api.models.page import Page
from redact_api.models.redaction_job import JobStatus, RedactionJob
from redact_api.models.span import SourceTier, Span
from redact_api.models.user import User


@pytest.fixture
def make_organization(session: AsyncSession) -> Callable[[], Awaitable[Organization]]:
    async def _make() -> Organization:
        org = Organization(name=f"Org {uuid4()}")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]
        return org

    return _make


@pytest.fixture
def make_user(session: AsyncSession) -> Callable[[], Awaitable[User]]:
    async def _make() -> User:
        user = User(name="Reviewer", email=f"reviewer-{uuid4()}@example.com")
        session.add(user)
        await session.flush()  # type: ignore[attr-defined]
        return user

    return _make


@pytest.fixture
def make_org_user(
    make_organization: Callable[[], Awaitable[Organization]],
    make_user: Callable[[], Awaitable[User]],
) -> Callable[[], Awaitable[tuple[Organization, User]]]:
    async def _make() -> tuple[Organization, User]:
        return await make_organization(), await make_user()

    return _make


@pytest.fixture
def make_document(session: AsyncSession) -> Callable[[UUID], Awaitable[Document]]:
    async def _make(organization_id: UUID) -> Document:
        document = Document(
            filename="doc.pdf",
            content_type="application/pdf",
            file_size=1024,
            organization_id=organization_id,
            storage_path=f"path/{uuid4()}",
            storage_url="http://storage/doc",
        )
        session.add(document)
        await session.flush()  # type: ignore[attr-defined]
        return document

    return _make


@pytest.fixture
def make_page(session: AsyncSession) -> Callable[..., Awaitable[Page]]:
    async def _make(document_id: UUID, page_number: int = 1) -> Page:
        page = Page(document_id=document_id, page_number=page_number)
        session.add(page)
        await session.flush()  # type: ignore[attr-defined]
        return page

    return _make


@pytest.fixture
def make_span(session: AsyncSession) -> Callable[..., Awaitable[Span]]:
    async def _make(
        page_id: UUID,
        *,
        text: str = "John Doe",
        bboxes: list[Any] | None = None,
        source_tier: SourceTier = SourceTier.TIER_1,
        confidence: float | None = 0.9,
    ) -> Span:
        span = Span(
            page_id=page_id,
            bboxes=[[1.0, 2.0, 3.0, 4.0]] if bboxes is None else bboxes,
            text=text,
            category="PERSON",
            source_tier=source_tier,
            confidence=confidence,
        )
        session.add(span)
        await session.flush()  # type: ignore[attr-defined]
        return span

    return _make


@pytest.fixture
def make_job(
    session: AsyncSession,
    make_document: Callable[[UUID], Awaitable[Document]],
) -> Callable[..., Awaitable[RedactionJob]]:
    async def _make(org: Organization, *, status: JobStatus = JobStatus.UPLOADED) -> RedactionJob:
        document = await make_document(org.id)
        job = RedactionJob(document_id=document.id, organization_id=org.id, status=status)
        session.add(job)
        await session.flush()  # type: ignore[attr-defined]
        return job

    return _make


@pytest.fixture
def add_span(
    make_page: Callable[..., Awaitable[Page]],
    make_span: Callable[..., Awaitable[Span]],
) -> Callable[..., Awaitable[Span]]:
    async def _add(job: RedactionJob, *, page_number: int = 1) -> Span:
        page = await make_page(job.document_id, page_number=page_number)
        return await make_span(page.id, bboxes=[], confidence=None)

    return _add
