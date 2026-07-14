"""Integration tests for the redaction-pipeline data model (redact-api#3).

Exercises the five new tables (Page, Span, Disposition, RedactionJob, AuditEntry)
against a real Postgres via the existing session/engine fixtures: FK cascade and
RESTRICT semantics, unique constraints, tenant scoping, enum round-trips, and
JSON/nullable column behavior.

Entity-creation factories (``make_organization``, ``make_user``, ``make_document``,
``make_page``, ``make_span``) are shared fixtures defined in ``conftest.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from redact_api.models.audit_entry import AuditAction, AuditEntry
from redact_api.models.disposition import Disposition, DispositionAction
from redact_api.models.document import Document
from redact_api.models.organization import Organization
from redact_api.models.page import Page
from redact_api.models.redaction_job import JobStatus, RedactionJob
from redact_api.models.span import SourceTier, Span
from redact_api.models.user import User

# Placeholder hash payloads: 64 hex chars, standing in for real SHA-256 digests.
HASH_A = "a" * 64
HASH_B = "b" * 64
GENESIS = "0" * 64

MakeOrganization = Callable[..., Awaitable[Organization]]
MakeUser = Callable[..., Awaitable[User]]
MakeDocument = Callable[..., Awaitable[Document]]
MakePage = Callable[..., Awaitable[Page]]
MakeSpan = Callable[..., Awaitable[Span]]


class TestRedactionModelChain:
    """Full-chain creation and aggregate-root constraints."""

    @pytest.mark.asyncio
    async def test_full_chain_creates(  # noqa: PLR0913 - pytest fixture params can't be restructured
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_user: MakeUser,
        make_document: MakeDocument,
        make_page: MakePage,
        make_span: MakeSpan,
    ) -> None:
        """Document -> RedactionJob -> Page -> Span -> Disposition creates with valid FKs."""
        org = await make_organization()
        user = await make_user()
        document = await make_document(org.id)
        job = RedactionJob(document_id=document.id, organization_id=org.id)
        session.add(job)
        page = await make_page(document.id)
        span = await make_span(page.id)
        disposition = Disposition(span_id=span.id, action=DispositionAction.APPROVED, reviewer_id=user.id)
        session.add(disposition)
        await session.commit()

        assert job.id is not None
        assert job.status == JobStatus.UPLOADED
        assert disposition.id is not None

    @pytest.mark.asyncio
    async def test_redaction_job_document_id_unique(
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_document: MakeDocument,
    ) -> None:
        """RedactionJob.document_id is UNIQUE (one job per document)."""
        org = await make_organization()
        document = await make_document(org.id)
        session.add(RedactionJob(document_id=document.id, organization_id=org.id))
        await session.flush()  # type: ignore[attr-defined]
        session.add(RedactionJob(document_id=document.id, organization_id=org.id))
        with pytest.raises(IntegrityError):
            await session.flush()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_page_document_page_number_unique(
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_document: MakeDocument,
        make_page: MakePage,
    ) -> None:
        """Page has a UNIQUE (document_id, page_number) constraint."""
        org = await make_organization()
        document = await make_document(org.id)
        await make_page(document.id, page_number=1)
        session.add(Page(document_id=document.id, page_number=1))
        with pytest.raises(IntegrityError):
            await session.flush()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_disposition_span_id_unique(  # noqa: PLR0913 - pytest fixture params can't be restructured
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_user: MakeUser,
        make_document: MakeDocument,
        make_page: MakePage,
        make_span: MakeSpan,
    ) -> None:
        """Disposition.span_id is UNIQUE (one disposition per span)."""
        org = await make_organization()
        user = await make_user()
        document = await make_document(org.id)
        page = await make_page(document.id)
        span = await make_span(page.id)
        session.add(Disposition(span_id=span.id, action=DispositionAction.APPROVED, reviewer_id=user.id))
        await session.flush()  # type: ignore[attr-defined]
        session.add(Disposition(span_id=span.id, action=DispositionAction.REJECTED, reviewer_id=user.id))
        with pytest.raises(IntegrityError):
            await session.flush()  # type: ignore[attr-defined]


class TestRedactionCascade:
    """Cascade and RESTRICT delete semantics (resolutions #8, #13)."""

    @pytest.mark.asyncio
    async def test_document_delete_cascades_through_span_disposition(  # noqa: PLR0913 - pytest fixture params can't be restructured
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_user: MakeUser,
        make_document: MakeDocument,
        make_page: MakePage,
        make_span: MakeSpan,
    ) -> None:
        """Deleting a Document cascades through Page -> Span -> Disposition."""
        org = await make_organization()
        user = await make_user()
        document = await make_document(org.id)
        page = await make_page(document.id)
        span = await make_span(page.id)
        session.add(Disposition(span_id=span.id, action=DispositionAction.APPROVED, reviewer_id=user.id))
        await session.commit()

        await session.delete(document)
        await session.commit()

        assert (await session.execute(select(func.count()).select_from(Page))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(Span))).scalar_one() == 0
        assert (await session.execute(select(func.count()).select_from(Disposition))).scalar_one() == 0

    @pytest.mark.asyncio
    async def test_delete_reviewer_referenced_by_disposition_restricts(  # noqa: PLR0913 - pytest fixture params can't be restructured
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_user: MakeUser,
        make_document: MakeDocument,
        make_page: MakePage,
        make_span: MakeSpan,
    ) -> None:
        """Deleting an app_user referenced by Disposition.reviewer_id raises IntegrityError."""
        org = await make_organization()
        user = await make_user()
        document = await make_document(org.id)
        page = await make_page(document.id)
        span = await make_span(page.id)
        session.add(Disposition(span_id=span.id, action=DispositionAction.APPROVED, reviewer_id=user.id))
        await session.commit()

        await session.delete(user)
        with pytest.raises(IntegrityError):
            await session.flush()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_delete_reviewer_referenced_by_audit_entry_restricts(
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_user: MakeUser,
        make_document: MakeDocument,
    ) -> None:
        """Deleting an app_user referenced by AuditEntry.reviewer_id raises IntegrityError."""
        org = await make_organization()
        user = await make_user()
        document = await make_document(org.id)
        job = RedactionJob(document_id=document.id, organization_id=org.id)
        session.add(job)
        await session.flush()  # type: ignore[attr-defined]
        session.add(
            AuditEntry(
                job_id=job.id,
                reviewer_id=user.id,
                organization_id=org.id,
                action=AuditAction.APPROVED,
                category="PERSON",
                text_hash=HASH_A,
                entry_hash=HASH_A,
                prev_hash=GENESIS,
                sequence=1,
            )
        )
        await session.commit()

        await session.delete(user)
        with pytest.raises(IntegrityError):
            await session.flush()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_delete_job_with_audit_entry_restricts(
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_user: MakeUser,
        make_document: MakeDocument,
    ) -> None:
        """Deleting a RedactionJob that has AuditEntry rows raises IntegrityError."""
        org = await make_organization()
        user = await make_user()
        document = await make_document(org.id)
        job = RedactionJob(document_id=document.id, organization_id=org.id)
        session.add(job)
        await session.flush()  # type: ignore[attr-defined]
        session.add(
            AuditEntry(
                job_id=job.id,
                reviewer_id=user.id,
                organization_id=org.id,
                action=AuditAction.APPROVED,
                category="PERSON",
                text_hash=HASH_A,
                entry_hash=HASH_A,
                prev_hash=GENESIS,
                sequence=1,
            )
        )
        await session.commit()

        await session.delete(job)
        with pytest.raises(IntegrityError):
            await session.flush()  # type: ignore[attr-defined]


class TestRedactionTenantScoping:
    """Single-table tenant scoping via denormalized organization_id (resolution #3)."""

    @pytest.mark.asyncio
    async def test_single_table_org_scoping(
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_user: MakeUser,
        make_document: MakeDocument,
    ) -> None:
        """RedactionJob and AuditEntry are filterable by organization_id with no joins."""
        org_a = await make_organization()
        org_b = await make_organization()
        user = await make_user()
        doc_a = await make_document(org_a.id)
        doc_b = await make_document(org_b.id)
        job_a = RedactionJob(document_id=doc_a.id, organization_id=org_a.id)
        job_b = RedactionJob(document_id=doc_b.id, organization_id=org_b.id)
        session.add_all([job_a, job_b])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]
        session.add(
            AuditEntry(
                job_id=job_a.id,
                reviewer_id=user.id,
                organization_id=org_a.id,
                action=AuditAction.APPROVED,
                category="PERSON",
                text_hash=HASH_A,
                entry_hash=HASH_A,
                prev_hash=GENESIS,
                sequence=1,
            )
        )
        await session.commit()

        jobs = (
            (await session.execute(select(RedactionJob).where(col(RedactionJob.organization_id) == org_a.id)))
            .scalars()
            .all()
        )
        assert [job.id for job in jobs] == [job_a.id]

        audits = (
            (await session.execute(select(AuditEntry).where(col(AuditEntry.organization_id) == org_a.id)))
            .scalars()
            .all()
        )
        assert len(audits) == 1
        assert audits[0].organization_id == org_a.id


class TestRedactionColumnBehavior:
    """Enum round-trips and JSON/nullable column behavior."""

    @pytest.mark.asyncio
    async def test_enum_round_trip(
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_user: MakeUser,
        make_document: MakeDocument,
        make_page: MakePage,
    ) -> None:
        """All four StrEnums persist and read back as their enum members (native_enum=False)."""
        org = await make_organization()
        user = await make_user()
        document = await make_document(org.id)
        page = await make_page(document.id)
        span = Span(
            page_id=page.id,
            bboxes=[],
            text="secret",
            category="PERSON",
            source_tier=SourceTier.TIER_2,
        )
        session.add(span)
        job = RedactionJob(document_id=document.id, organization_id=org.id, status=JobStatus.DETECTED)
        session.add(job)
        await session.flush()  # type: ignore[attr-defined]
        disposition = Disposition(span_id=span.id, action=DispositionAction.REJECTED, reviewer_id=user.id)
        session.add(disposition)
        audit = AuditEntry(
            job_id=job.id,
            reviewer_id=user.id,
            organization_id=org.id,
            action=AuditAction.MANUAL_SPAN_ADDED,
            category="PERSON",
            text_hash=HASH_A,
            entry_hash=HASH_B,
            prev_hash=GENESIS,
            sequence=1,
        )
        session.add(audit)
        await session.commit()

        for obj in (span, job, disposition, audit):
            await session.refresh(obj)
        assert span.source_tier == SourceTier.TIER_2
        assert job.status == JobStatus.DETECTED
        assert disposition.action == DispositionAction.REJECTED
        assert audit.action == AuditAction.MANUAL_SPAN_ADDED

    @pytest.mark.asyncio
    async def test_span_bboxes_json_and_nullable_confidence(
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_document: MakeDocument,
        make_page: MakePage,
    ) -> None:
        """Span.bboxes round-trips an arbitrary JSON list; Span.confidence accepts None."""
        org = await make_organization()
        document = await make_document(org.id)
        page = await make_page(document.id)
        bboxes = [[10.5, 20.0, 30.0, 40.0], [1.0, 2.0, 3.0, 4.0]]
        span = Span(
            page_id=page.id,
            bboxes=bboxes,
            text="secret",
            category="PERSON",
            source_tier=SourceTier.TIER_3,
            confidence=None,
        )
        session.add(span)
        await session.commit()
        await session.refresh(span)

        assert span.bboxes == bboxes
        assert span.confidence is None

    @pytest.mark.asyncio
    async def test_audit_entry_span_id_nullable(
        self,
        session: AsyncSession,
        make_organization: MakeOrganization,
        make_user: MakeUser,
        make_document: MakeDocument,
    ) -> None:
        """AuditEntry.span_id accepts None for a job-level event."""
        org = await make_organization()
        user = await make_user()
        document = await make_document(org.id)
        job = RedactionJob(document_id=document.id, organization_id=org.id)
        session.add(job)
        await session.flush()  # type: ignore[attr-defined]
        audit = AuditEntry(
            job_id=job.id,
            span_id=None,
            reviewer_id=user.id,
            organization_id=org.id,
            action=AuditAction.EDITED,
            category="PERSON",
            text_hash=HASH_A,
            entry_hash=HASH_B,
            prev_hash=GENESIS,
            sequence=1,
        )
        session.add(audit)
        await session.commit()
        await session.refresh(audit)

        assert audit.span_id is None
