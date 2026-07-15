"""Integration tests for the ingest_job task (redact-api#8).

Drives ``ingest_job`` directly against a real database and an in-memory storage double,
covering the happy path (UPLOADED -> INGESTED + chain enqueue), an ingest rejection
(-> FAILED, no chain), and guard-first redelivery (no-op ACK on an already-advanced job).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from redact_api.models.activity_log import ActivityLog
from redact_api.models.organization import Organization
from redact_api.models.page import Page
from redact_api.models.redaction_job import JobStatus, RedactionJob
from redact_api.models.span import Span
from redact_api.storage import keys
from redact_api.tasks import ingest_job as ingest_job_module
from redact_api.tasks.detect_job import detect_job
from redact_api.tasks.ingest_job import ingest_job
from redact_api.tests.conftest import FakeStorageClient
from redact_api.tests.fixtures.ingest_pdfs import build_malformed_pdf, build_multi_page_pdf

SessionMaker = async_sessionmaker[AsyncSession]

MakeOrg = Callable[[], Awaitable[Organization]]
MakeJob = Callable[..., Awaitable[RedactionJob]]


async def _count(session_maker: SessionMaker, model: type, **filters: object) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    async with session_maker() as check:
        return (await check.execute(stmt)).scalar_one()


async def _status(session_maker: SessionMaker, job_id: UUID) -> JobStatus:
    async with session_maker() as check:
        return (await check.execute(select(RedactionJob).where(RedactionJob.id == job_id))).scalar_one().status


@pytest.fixture
def wire_ingest(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeStorageClient, AsyncMock]:
    """Wire ingest_job to an in-memory storage double and stub the detect_job chain enqueue."""
    storage = FakeStorageClient()
    detect_kiq = AsyncMock()
    monkeypatch.setattr(ingest_job_module, "build_storage_client", lambda: storage)
    monkeypatch.setattr(detect_job, "kiq", detect_kiq)
    return storage, detect_kiq


class TestIngestJob:
    async def test_happy_path_ingests_and_chains(
        self,
        session: AsyncSession,
        session_maker: SessionMaker,
        make_organization: MakeOrg,
        make_job: MakeJob,
        wire_ingest: tuple[FakeStorageClient, AsyncMock],
    ) -> None:
        storage, detect_kiq = wire_ingest
        org = await make_organization()
        job = await make_job(org)
        await session.commit()
        storage.uploads[keys.original_pdf_key(job.document_id)] = build_multi_page_pdf(page_count=1)

        await ingest_job(job_id=str(job.id))

        assert await _status(session_maker, job.id) == JobStatus.INGESTED
        assert await _count(session_maker, ActivityLog, resource_id=job.id) == 1
        detect_kiq.assert_awaited_once_with(job_id=str(job.id))
        # Per-page artifacts were staged.
        assert keys.page_raster_key(job.document_id, 1) in storage.uploads

    async def test_rejection_marks_failed_and_does_not_chain(
        self,
        session: AsyncSession,
        session_maker: SessionMaker,
        make_organization: MakeOrg,
        make_job: MakeJob,
        wire_ingest: tuple[FakeStorageClient, AsyncMock],
    ) -> None:
        storage, detect_kiq = wire_ingest
        org = await make_organization()
        job = await make_job(org)
        await session.commit()
        storage.uploads[keys.original_pdf_key(job.document_id)] = build_malformed_pdf()

        await ingest_job(job_id=str(job.id))

        assert await _status(session_maker, job.id) == JobStatus.FAILED
        assert await _count(session_maker, ActivityLog, resource_id=job.id) == 1
        detect_kiq.assert_not_awaited()

    async def test_redelivery_is_noop(
        self,
        session: AsyncSession,
        session_maker: SessionMaker,
        make_organization: MakeOrg,
        make_job: MakeJob,
        wire_ingest: tuple[FakeStorageClient, AsyncMock],
    ) -> None:
        _storage, detect_kiq = wire_ingest
        org = await make_organization()
        job = await make_job(org, status=JobStatus.INGESTED)
        await session.commit()

        await ingest_job(job_id=str(job.id))

        assert await _status(session_maker, job.id) == JobStatus.INGESTED
        assert await _count(session_maker, ActivityLog, resource_id=job.id) == 0
        assert await _count(session_maker, Span) == 0
        assert await _count(session_maker, Page) == 0
        detect_kiq.assert_not_awaited()
