"""Integration tests for the apply_job task (redact-api#8).

Drives ``apply_job`` directly against a real database and an in-memory storage double. The
pure ``apply`` burn-in/verify is stubbed (covered by test_apply) so these tests focus on the
task's own orchestration: the verify PASS/FAIL landing states, a malformed-bbox projection
failure, and guard-first redelivery.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq import InMemoryBroker

from redact_api.models.activity_log import ActivityLog
from redact_api.models.disposition import Disposition, DispositionAction
from redact_api.models.organization import Organization
from redact_api.models.page import Page
from redact_api.models.redaction_job import JobStatus, RedactionJob
from redact_api.models.span import SourceTier, Span
from redact_api.redaction.models import ApplyResult, ApprovedSpan, VerifyResult, VerifyVerdict
from redact_api.storage import keys
from redact_api.tasks import apply_job as apply_job_module
from redact_api.tasks.apply_job import apply_job
from redact_api.tests.conftest import FakeStorageClient
from redact_api.tests.fixtures.ingest_pdfs import build_multi_page_pdf

SessionMaker = async_sessionmaker[AsyncSession]

MakeOrg = Callable[[], Awaitable[Organization]]
MakeJob = Callable[..., Awaitable[RedactionJob]]

DEFAULT_REVIEWER_ID = UUID("00000000-0000-0000-0000-000000000001")


async def _count(session_maker: SessionMaker, model: type, **filters: object) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    async with session_maker() as check:
        return (await check.execute(stmt)).scalar_one()


async def _fetch_job(session_maker: SessionMaker, job_id: UUID) -> RedactionJob:
    async with session_maker() as check:
        return (await check.execute(select(RedactionJob).where(RedactionJob.id == job_id))).scalar_one()


def _passing_apply(_pdf_bytes: bytes, _spans: list[ApprovedSpan]) -> ApplyResult:
    return ApplyResult(
        pdf_bytes=b"redacted", verify_result=VerifyResult(verdict=VerifyVerdict.PASS, checks=[], findings=[])
    )


def _failing_apply(_pdf_bytes: bytes, _spans: list[ApprovedSpan]) -> ApplyResult:
    return ApplyResult(
        pdf_bytes=b"redacted", verify_result=VerifyResult(verdict=VerifyVerdict.FAIL, checks=[], findings=[])
    )


async def _seed_approved_span(session: AsyncSession, job: RedactionJob, *, bboxes: list[list[float]]) -> None:
    page = Page(document_id=job.document_id, page_number=1)
    session.add(page)
    await session.flush()  # type: ignore[attr-defined]
    span = Span(
        page_id=page.id, bboxes=bboxes, text="John Doe", category="name", source_tier=SourceTier.TIER_1, confidence=0.9
    )
    session.add(span)
    await session.flush()  # type: ignore[attr-defined]
    session.add(Disposition(span_id=span.id, action=DispositionAction.APPROVED, reviewer_id=DEFAULT_REVIEWER_ID))
    await session.flush()  # type: ignore[attr-defined]


@pytest.fixture
def wire_apply(monkeypatch: pytest.MonkeyPatch) -> FakeStorageClient:
    """Wire apply_job to an in-memory storage double.

    Individual tests stub ``apply_job_module.apply`` directly via ``monkeypatch``.
    """
    storage = FakeStorageClient()
    monkeypatch.setattr(apply_job_module, "build_storage_client", lambda: storage)
    return storage


class TestApplyJob:
    async def test_verify_pass_lands_verified(  # noqa: PLR0913 - fixture params
        self,
        session: AsyncSession,
        session_maker: SessionMaker,
        make_organization: MakeOrg,
        make_job: MakeJob,
        wire_apply: FakeStorageClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(apply_job_module, "apply", _passing_apply)
        org = await make_organization()
        job = await make_job(org, status=JobStatus.APPLYING)
        await session.commit()
        wire_apply.uploads[keys.original_pdf_key(job.document_id)] = build_multi_page_pdf(page_count=1)

        await apply_job(job_id=str(job.id))

        refreshed = await _fetch_job(session_maker, job.id)
        assert refreshed.status == JobStatus.VERIFIED
        assert refreshed.redacted_pdf_key == keys.redacted_pdf_key(job.id)
        assert keys.redacted_pdf_key(job.id) in wire_apply.uploads
        assert await _count(session_maker, ActivityLog, resource_id=job.id) == 1

    async def test_verify_fail_lands_failed_without_raising(  # noqa: PLR0913 - fixture params
        self,
        session: AsyncSession,
        session_maker: SessionMaker,
        make_organization: MakeOrg,
        make_job: MakeJob,
        wire_apply: FakeStorageClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(apply_job_module, "apply", _failing_apply)
        org = await make_organization()
        job = await make_job(org, status=JobStatus.APPLYING)
        await session.commit()
        wire_apply.uploads[keys.original_pdf_key(job.document_id)] = build_multi_page_pdf(page_count=1)

        await apply_job(job_id=str(job.id))

        refreshed = await _fetch_job(session_maker, job.id)
        assert refreshed.status == JobStatus.FAILED
        assert refreshed.redacted_pdf_key is None
        assert keys.redacted_pdf_key(job.id) not in wire_apply.uploads
        assert await _count(session_maker, ActivityLog, resource_id=job.id) == 1

    async def test_malformed_bbox_marks_failed_and_reraises(
        self,
        session: AsyncSession,
        session_maker: SessionMaker,
        make_organization: MakeOrg,
        make_job: MakeJob,
        wire_apply: FakeStorageClient,
    ) -> None:
        org = await make_organization()
        job = await make_job(org, status=JobStatus.APPLYING)
        await _seed_approved_span(session, job, bboxes=[[1.0, 2.0, 3.0]])
        await session.commit()
        wire_apply.uploads[keys.original_pdf_key(job.document_id)] = build_multi_page_pdf(page_count=1)

        with pytest.raises(ValidationError):
            await apply_job(job_id=str(job.id))

        refreshed = await _fetch_job(session_maker, job.id)
        assert refreshed.status == JobStatus.FAILED
        assert await _count(session_maker, ActivityLog, resource_id=job.id) == 1

    async def test_redelivery_is_noop(
        self,
        session: AsyncSession,
        session_maker: SessionMaker,
        make_organization: MakeOrg,
        make_job: MakeJob,
        wire_apply: FakeStorageClient,
    ) -> None:
        org = await make_organization()
        job = await make_job(org, status=JobStatus.VERIFIED)
        await session.commit()

        await apply_job(job_id=str(job.id))

        refreshed = await _fetch_job(session_maker, job.id)
        assert refreshed.status == JobStatus.VERIFIED
        assert await _count(session_maker, ActivityLog, resource_id=job.id) == 0
        assert keys.redacted_pdf_key(job.id) not in wire_apply.uploads

    async def test_via_broker_kiq_applies_through_middleware_pipeline(  # noqa: PLR0913 - fixture params
        self,
        session: AsyncSession,
        session_maker: SessionMaker,
        make_organization: MakeOrg,
        make_job: MakeJob,
        wire_apply: FakeStorageClient,
        monkeypatch: pytest.MonkeyPatch,
        test_broker: InMemoryBroker,
    ) -> None:
        """Drive apply_job through the real broker (``.kiq()`` + ``.wait_result()``), not a
        direct call, so the middleware pipeline (job context, logging, metrics) actually
        runs -- this is what would have caught the MetricsMiddleware double-counting bug
        before it shipped, since a direct call bypasses middleware entirely.
        """
        assert test_broker is not None  # confirms TASKIQ_ENV=test wired the in-memory broker
        monkeypatch.setattr(apply_job_module, "apply", _passing_apply)
        org = await make_organization()
        job = await make_job(org, status=JobStatus.APPLYING)
        await session.commit()
        wire_apply.uploads[keys.original_pdf_key(job.document_id)] = build_multi_page_pdf(page_count=1)

        task = await apply_job.kiq(job_id=str(job.id))
        result = await task.wait_result(check_interval=0.01)

        assert not result.is_err
        refreshed = await _fetch_job(session_maker, job.id)
        assert refreshed.status == JobStatus.VERIFIED
