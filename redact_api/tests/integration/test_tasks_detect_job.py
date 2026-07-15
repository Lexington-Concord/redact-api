"""Integration tests for the detect_job task (redact-api#8).

Drives ``detect_job`` directly against a real database and an in-memory storage double,
covering the happy path (INGESTED -> IN_REVIEW with real Tier-1+Tier-2 detection persisting
spans), a detection failure (-> FAILED, re-raised), and guard-first redelivery (no-op ACK).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
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
from redact_api.tasks import detect_job as detect_job_module
from redact_api.tasks.detect_job import detect_job
from redact_api.tests.conftest import FakeStorageClient
from redact_api.tests.fixtures.ingest_pdfs import build_pii_sample_pdf

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


async def _span_count_for_document(session_maker: SessionMaker, document_id: UUID) -> int:
    async with session_maker() as check:
        stmt = (
            select(func.count())
            .select_from(Span)
            .join(Page, Span.page_id == Page.id)
            .where(Page.document_id == document_id)
        )
        return (await check.execute(stmt)).scalar_one()


@pytest.fixture
def wire_detect(monkeypatch: pytest.MonkeyPatch) -> FakeStorageClient:
    """Wire detect_job to an in-memory storage double."""
    storage = FakeStorageClient()
    monkeypatch.setattr(detect_job_module, "build_storage_client", lambda: storage)
    return storage


class TestDetectJob:
    async def test_happy_path_detects_and_advances_to_in_review(
        self,
        session: AsyncSession,
        session_maker: SessionMaker,
        make_organization: MakeOrg,
        make_job: MakeJob,
        wire_detect: FakeStorageClient,
    ) -> None:
        org = await make_organization()
        job = await make_job(org, status=JobStatus.INGESTED)
        await session.commit()
        wire_detect.uploads[keys.original_pdf_key(job.document_id)] = build_pii_sample_pdf()

        await detect_job(job_id=str(job.id))

        assert await _status(session_maker, job.id) == JobStatus.IN_REVIEW
        assert await _span_count_for_document(session_maker, job.document_id) > 0
        assert await _count(session_maker, ActivityLog, resource_id=job.id) == 1

    async def test_detection_failure_marks_failed_and_reraises(  # noqa: PLR0913 - fixture params
        self,
        session: AsyncSession,
        session_maker: SessionMaker,
        make_organization: MakeOrg,
        make_job: MakeJob,
        wire_detect: FakeStorageClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        org = await make_organization()
        job = await make_job(org, status=JobStatus.INGESTED)
        await session.commit()
        wire_detect.uploads[keys.original_pdf_key(job.document_id)] = build_pii_sample_pdf()

        boom_msg = "detection exploded"

        async def _boom(*_args: object, **_kwargs: object) -> int:
            raise RuntimeError(boom_msg)

        monkeypatch.setattr(detect_job_module, "run_detection", _boom)

        with pytest.raises(RuntimeError, match="detection exploded"):
            await detect_job(job_id=str(job.id))

        assert await _status(session_maker, job.id) == JobStatus.FAILED
        assert await _count(session_maker, ActivityLog, resource_id=job.id) == 1

    async def test_redelivery_is_noop(
        self,
        session: AsyncSession,
        session_maker: SessionMaker,
        make_organization: MakeOrg,
        make_job: MakeJob,
        wire_detect: FakeStorageClient,
    ) -> None:
        org = await make_organization()
        job = await make_job(org, status=JobStatus.DETECTED)
        await session.commit()

        await detect_job(job_id=str(job.id))

        assert await _status(session_maker, job.id) == JobStatus.DETECTED
        assert await _span_count_for_document(session_maker, job.document_id) == 0
        assert await _count(session_maker, ActivityLog, resource_id=job.id) == 0
