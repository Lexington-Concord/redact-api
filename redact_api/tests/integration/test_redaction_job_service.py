"""Integration tests for redaction_job_service (redact-api#3).

Covers the job-status state machine (transition_job_status + InvalidStateTransitionError),
the undispositioned-span gate before APPLYING (UndispositionedSpansError), and the
append-only SHA-256 audit hash chain (append_audit_entry), all against real Postgres.
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.models.audit_entry import AuditAction
from redact_api.models.disposition import Disposition, DispositionAction
from redact_api.models.document import Document
from redact_api.models.organization import Organization
from redact_api.models.page import Page
from redact_api.models.redaction_job import JobStatus, RedactionJob
from redact_api.models.span import SourceTier, Span
from redact_api.models.user import User
from redact_api.services.redaction_job_service import (
    GENESIS_PREV_HASH,
    VALID_TRANSITIONS,
    AuditEntryInput,
    InvalidStateTransitionError,
    UndispositionedSpansError,
    append_audit_entry,
    transition_job_status,
)

LINEAR_CHAIN = [
    JobStatus.UPLOADED,
    JobStatus.INGESTED,
    JobStatus.DETECTED,
    JobStatus.IN_REVIEW,
    JobStatus.APPLYING,
    JobStatus.VERIFIED,
    JobStatus.EXPORTED,
]
NON_TERMINAL = LINEAR_CHAIN[:-1]


def _expected_entry_hash(entry: object) -> str:
    """Recompute the canonical entry hash independently from a persisted entry."""
    payload = {
        "action": entry.action.value,  # type: ignore[attr-defined]
        "category": entry.category,  # type: ignore[attr-defined]
        "created_at": entry.created_at.isoformat(),  # type: ignore[attr-defined]
        "reviewer": str(entry.reviewer_id),  # type: ignore[attr-defined]
        "span_id": str(entry.span_id) if entry.span_id is not None else None,  # type: ignore[attr-defined]
        "text_hash": entry.text_hash,  # type: ignore[attr-defined]
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((entry.prev_hash + canonical).encode("utf-8")).hexdigest()  # type: ignore[attr-defined]


async def _make_org_user(session: AsyncSession) -> tuple[Organization, User]:
    org = Organization(name=f"Org {uuid4()}")
    user = User(name="Reviewer", email=f"reviewer-{uuid4()}@example.com")
    session.add_all([org, user])  # type: ignore[attr-defined]
    await session.flush()  # type: ignore[attr-defined]
    return org, user


async def _make_job(
    session: AsyncSession,
    org: Organization,
    *,
    status: JobStatus = JobStatus.UPLOADED,
) -> RedactionJob:
    document = Document(
        filename="doc.pdf",
        content_type="application/pdf",
        file_size=1024,
        organization_id=org.id,
        storage_path=f"path/{uuid4()}",
        storage_url="http://storage/doc",
    )
    session.add(document)
    await session.flush()  # type: ignore[attr-defined]
    job = RedactionJob(document_id=document.id, organization_id=org.id, status=status)
    session.add(job)
    await session.flush()  # type: ignore[attr-defined]
    return job


async def _add_span(session: AsyncSession, job: RedactionJob, *, page_number: int = 1) -> Span:
    page = Page(document_id=job.document_id, page_number=page_number)
    session.add(page)
    await session.flush()  # type: ignore[attr-defined]
    span = Span(
        page_id=page.id,
        bboxes=[],
        text="John Doe",
        category="PERSON",
        source_tier=SourceTier.TEXT_LAYER,
    )
    session.add(span)
    await session.flush()  # type: ignore[attr-defined]
    return span


class TestTransitionJobStatus:
    """State-machine transitions (resolution #4)."""

    @pytest.mark.asyncio
    async def test_linear_chain_allowed(self, session: AsyncSession) -> None:
        """Every step of the linear chain is permitted end to end."""
        org, _ = await _make_org_user(session)
        job = await _make_job(session, org)
        for target in LINEAR_CHAIN[1:]:
            await transition_job_status(session, job, target)
            assert job.status == target

    @pytest.mark.asyncio
    async def test_any_non_terminal_to_failed(self, session: AsyncSession) -> None:
        """Any non-terminal state may transition to FAILED."""
        org, _ = await _make_org_user(session)
        for state in NON_TERMINAL:
            job = await _make_job(session, org, status=state)
            await transition_job_status(session, job, JobStatus.FAILED)
            assert job.status == JobStatus.FAILED

    @pytest.mark.asyncio
    async def test_out_of_order_rejected(self, session: AsyncSession) -> None:
        """A non-adjacent jump raises InvalidStateTransitionError."""
        org, _ = await _make_org_user(session)
        job = await _make_job(session, org, status=JobStatus.UPLOADED)
        with pytest.raises(InvalidStateTransitionError):
            await transition_job_status(session, job, JobStatus.APPLYING)
        assert job.status == JobStatus.UPLOADED

    @pytest.mark.asyncio
    async def test_failed_is_terminal(self, session: AsyncSession) -> None:
        """FAILED has an empty transition set (no retry edge)."""
        assert VALID_TRANSITIONS[JobStatus.FAILED] == frozenset()
        org, _ = await _make_org_user(session)
        job = await _make_job(session, org, status=JobStatus.FAILED)
        with pytest.raises(InvalidStateTransitionError):
            await transition_job_status(session, job, JobStatus.INGESTED)


class TestUndispositionedGate:
    """The APPLYING gate requires every span to be dispositioned (resolution #9)."""

    @pytest.mark.asyncio
    async def test_applying_blocked_by_undispositioned_span(self, session: AsyncSession) -> None:
        """Transitioning to APPLYING with an undispositioned span raises and leaves status unchanged."""
        org, _ = await _make_org_user(session)
        job = await _make_job(session, org, status=JobStatus.IN_REVIEW)
        await _add_span(session, job)
        with pytest.raises(UndispositionedSpansError):
            await transition_job_status(session, job, JobStatus.APPLYING)
        assert job.status == JobStatus.IN_REVIEW

    @pytest.mark.asyncio
    async def test_applying_allowed_when_all_dispositioned(self, session: AsyncSession) -> None:
        """Transitioning to APPLYING succeeds once every span has a Disposition."""
        org, user = await _make_org_user(session)
        job = await _make_job(session, org, status=JobStatus.IN_REVIEW)
        span = await _add_span(session, job)
        session.add(Disposition(span_id=span.id, action=DispositionAction.APPROVED, reviewer_id=user.id))
        await session.flush()  # type: ignore[attr-defined]
        await transition_job_status(session, job, JobStatus.APPLYING)
        assert job.status == JobStatus.APPLYING


class TestAuditHashChain:
    """Append-only SHA-256 hash chain (resolutions #6, #7, #12)."""

    @pytest.mark.asyncio
    async def test_genesis_prev_hash(self, session: AsyncSession) -> None:
        """The first audit entry for a job uses the genesis prev_hash."""
        org, user = await _make_org_user(session)
        job = await _make_job(session, org)
        entry = await append_audit_entry(
            session,
            job.id,
            AuditEntryInput(action=AuditAction.APPROVED, category="PERSON", text="John Doe", reviewer_id=user.id),
        )
        assert entry.prev_hash == GENESIS_PREV_HASH
        assert GENESIS_PREV_HASH == "0" * 64

    @pytest.mark.asyncio
    async def test_second_entry_links_to_first(self, session: AsyncSession) -> None:
        """The second entry's prev_hash equals the first entry's entry_hash."""
        org, user = await _make_org_user(session)
        job = await _make_job(session, org)
        first = await append_audit_entry(
            session,
            job.id,
            AuditEntryInput(action=AuditAction.APPROVED, category="PERSON", text="John Doe", reviewer_id=user.id),
        )
        second = await append_audit_entry(
            session,
            job.id,
            AuditEntryInput(action=AuditAction.REJECTED, category="EMAIL", text="a@b.com", reviewer_id=user.id),
        )
        assert second.prev_hash == first.entry_hash
        assert second.sequence > first.sequence

    @pytest.mark.asyncio
    async def test_entry_hash_matches_golden(self, session: AsyncSession) -> None:
        """entry_hash equals SHA-256(prev_hash + canonical_json(6-key payload))."""
        org, user = await _make_org_user(session)
        job = await _make_job(session, org)
        span = await _add_span(session, job)
        entry = await append_audit_entry(
            session,
            job.id,
            AuditEntryInput(
                action=AuditAction.APPROVED,
                category="PERSON",
                text="John Doe",
                reviewer_id=user.id,
                span_id=span.id,
            ),
        )
        assert entry.entry_hash == _expected_entry_hash(entry)

    @pytest.mark.asyncio
    async def test_no_raw_text_only_hash(self, session: AsyncSession) -> None:
        """An audit entry stores only category + a 64-hex digest, never raw span text."""
        org, user = await _make_org_user(session)
        job = await _make_job(session, org)
        raw = "John Doe"
        entry = await append_audit_entry(
            session,
            job.id,
            AuditEntryInput(action=AuditAction.APPROVED, category="PERSON", text=raw, reviewer_id=user.id),
        )
        assert "text" not in type(entry).model_fields
        assert entry.category == "PERSON"
        assert len(entry.text_hash) == 64
        assert entry.text_hash != raw
        assert int(entry.text_hash, 16) >= 0  # valid hex

    @pytest.mark.asyncio
    async def test_normalization_reuse(self, session: AsyncSession) -> None:
        """Case/whitespace-equivalent strings hash identically via the imported normalize_text."""
        org, user = await _make_org_user(session)
        job_a = await _make_job(session, org)
        job_b = await _make_job(session, org)
        entry_a = await append_audit_entry(
            session,
            job_a.id,
            AuditEntryInput(action=AuditAction.APPROVED, category="PERSON", text="John   Doe", reviewer_id=user.id),
        )
        entry_b = await append_audit_entry(
            session,
            job_b.id,
            AuditEntryInput(action=AuditAction.APPROVED, category="PERSON", text="  john doe  ", reviewer_id=user.id),
        )
        assert entry_a.text_hash == entry_b.text_hash

    @pytest.mark.asyncio
    async def test_organization_id_sourced_from_job(self, session: AsyncSession) -> None:
        """AuditEntry.organization_id is derived from the loaded job, not a caller argument."""
        org, user = await _make_org_user(session)
        job = await _make_job(session, org)
        entry = await append_audit_entry(
            session,
            job.id,
            AuditEntryInput(action=AuditAction.APPROVED, category="PERSON", text="John Doe", reviewer_id=user.id),
        )
        assert entry.organization_id == org.id

    @pytest.mark.asyncio
    async def test_audit_action_values_persist(self, session: AsyncSession) -> None:
        """Each AuditAction value is accepted and persisted (resolution #12)."""
        org, user = await _make_org_user(session)
        job = await _make_job(session, org)
        actions = [
            AuditAction.APPROVED,
            AuditAction.REJECTED,
            AuditAction.EDITED,
            AuditAction.MANUAL_SPAN_ADDED,
        ]
        for action in actions:
            entry = await append_audit_entry(
                session,
                job.id,
                AuditEntryInput(action=action, category="PERSON", text="John Doe", reviewer_id=user.id),
            )
            assert entry.action == action
