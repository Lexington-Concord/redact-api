"""Shared entity-factory fixtures for the redaction-pipeline integration tests.

Provides factory-as-fixture callables (each closes over the ``session`` fixture and
returns an async callable) so tests share entity-construction logic while still passing
call-time arguments (organization id, page number, custom ``source_tier``, etc.).
Consolidates the near-duplicate ``_make_*`` helpers previously authored independently
in ``test_redaction_models.py`` and ``test_redaction_job_service.py``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.models.audit_entry import AuditAction
from redact_api.models.document import Document
from redact_api.models.organization import Organization
from redact_api.models.page import Page
from redact_api.models.redaction_job import JobStatus, RedactionJob
from redact_api.models.span import SourceTier, Span
from redact_api.models.user import User
from redact_api.services.redaction_job_service import (
    JOB_LIFECYCLE_CATEGORY,
    AuditEntryInput,
    append_audit_entry,
)
from redact_api.storage import keys
from redact_api.tests.conftest import FakeStorageClient

# Fixed tenant ids matching the autouse ``default_auth_user_in_org`` fixture, so
# ``seed_verified_job`` works for both the HTTP-client-based ``TestExport`` and the
# direct-session-based export-manifest-service test. These are additive: they deliberately
# do NOT alias the per-file DEFAULT_* constants already defined in test_jobs_api.py /
# test_tasks_apply_job.py -- those stay local to their own modules.
DEFAULT_ORG_ID = UUID("00000000-0000-0000-0000-000000000000")
DEFAULT_REVIEWER_ID = UUID("00000000-0000-0000-0000-000000000001")

# A digest-only verify verdict blob, JSON-encoded into the VERIFY_PASSED entry's ``category``
# column exactly as ``apply_job`` writes it -- the manifest service parses this back out.
SEED_VERIFY_SUMMARY: dict[str, Any] = {
    "verdict": "pass",
    "checks": [
        {"check_type": "text_layer", "passed": True, "pages_checked": 1},
        {"check_type": "ocr", "passed": True, "pages_checked": 1},
        {"check_type": "metadata", "passed": True, "pages_checked": 1},
    ],
}
SEED_ORIGINAL_PDF_BYTES = b"%PDF-original"
SEED_REDACTED_PDF_BYTES = b"%PDF-redacted"


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


@pytest.fixture
def seed_verified_job(session: AsyncSession) -> Callable[[FakeStorageClient], Awaitable[RedactionJob]]:
    """Seed a committed VERIFIED job whose audit chain and stored PDFs an export can consume.

    Builds, in ``sequence`` order: one span-level APPROVED entry, one job-level APPLY_STARTED
    entry, one job-level VERIFY_PASSED entry (its ``category`` a JSON-encoded verdict blob).
    Seeds original + redacted PDF bytes into the caller-supplied storage double so both the
    HTTP export test (which passes the app-wired ``fake_storage_client``) and the manifest
    service test (which passes its own double) share one seeding path. The job's own EXPORTED
    entry is intentionally NOT seeded -- export appends it after manifest assembly.
    """

    async def _seed(storage: FakeStorageClient) -> RedactionJob:
        document = Document(
            filename="doc.pdf",
            content_type="application/pdf",
            file_size=1024,
            organization_id=DEFAULT_ORG_ID,
            storage_path="k",
            storage_url="k",
        )
        session.add(document)
        await session.flush()  # type: ignore[attr-defined]

        job = RedactionJob(
            document_id=document.id,
            organization_id=DEFAULT_ORG_ID,
            status=JobStatus.VERIFIED,
        )
        session.add(job)
        await session.flush()  # type: ignore[attr-defined]  # assign job.id before keying the redacted PDF
        job.redacted_pdf_key = keys.redacted_pdf_key(job.id)
        session.add(job)
        await session.flush()  # type: ignore[attr-defined]

        page = Page(document_id=document.id, page_number=1)
        session.add(page)
        await session.flush()  # type: ignore[attr-defined]
        span = Span(
            page_id=page.id,
            bboxes=[[1.0, 2.0, 3.0, 4.0]],
            text="John Doe",
            category="PERSON",
            source_tier=SourceTier.TIER_1,
            confidence=0.9,
        )
        session.add(span)
        await session.flush()  # type: ignore[attr-defined]

        await append_audit_entry(
            session,
            job.id,
            AuditEntryInput(
                action=AuditAction.APPROVED,
                category="PERSON",
                text="John Doe",
                reviewer_id=DEFAULT_REVIEWER_ID,
                span_id=span.id,
            ),
        )
        await append_audit_entry(
            session,
            job.id,
            AuditEntryInput(
                action=AuditAction.APPLY_STARTED,
                category=JOB_LIFECYCLE_CATEGORY,
                text=None,
                reviewer_id=DEFAULT_REVIEWER_ID,
            ),
        )
        await append_audit_entry(
            session,
            job.id,
            AuditEntryInput(
                action=AuditAction.VERIFY_PASSED,
                category=json.dumps(SEED_VERIFY_SUMMARY, sort_keys=True, separators=(",", ":")),
                text=None,
                reviewer_id=DEFAULT_REVIEWER_ID,
            ),
        )
        await session.commit()

        storage.uploads[keys.original_pdf_key(document.id)] = SEED_ORIGINAL_PDF_BYTES
        storage.uploads[keys.redacted_pdf_key(job.id)] = SEED_REDACTED_PDF_BYTES
        return job

    return _seed
