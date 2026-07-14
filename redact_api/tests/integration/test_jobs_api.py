"""HTTP integration tests for the redaction-job API surface (redact-api#7).

Covers the six endpoints end-to-end against real Postgres + the in-memory storage
double: upload/ingest, get + tenant isolation, span listing, the disposition batch
(re-disposition, idempotent no-op, reviewer_id-injection rejection, wrong-state 409),
apply (zero-span verify PASS, undispositioned/wrong-state 409, malformed-bbox 422,
verify-FAIL 422, RBAC 403) and export (gating, idempotent re-read, RBAC 403).

Rows are seeded through the ``session`` fixture (committed so the endpoints' own request
sessions observe them); post-request state is asserted through a *fresh* session from
``session_maker`` to avoid stale identity-map reads.
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from redact_api.models.audit_entry import AuditEntry
from redact_api.models.disposition import Disposition, DispositionAction
from redact_api.models.document import Document
from redact_api.models.membership import Membership, MembershipRole
from redact_api.models.organization import Organization
from redact_api.models.page import Page
from redact_api.models.redaction_job import JobStatus, RedactionJob
from redact_api.models.span import SourceTier, Span
from redact_api.models.user import User
from redact_api.redaction.models import (
    ApplyResult,
    ApprovedSpan,
    CheckSummary,
    CheckType,
    VerifyFinding,
    VerifyResult,
    VerifyVerdict,
)
from redact_api.storage import keys
from redact_api.tests.conftest import FakeStorageClient
from redact_api.tests.fixtures.apply_pdfs import make_pii_source_pdf
from redact_api.tests.fixtures.ingest_pdfs import (
    build_encrypted_pdf,
    build_malformed_pdf,
    build_mixed_native_and_image_pdf,
    build_multi_page_pdf,
)

DEFAULT_ORG_ID = UUID("00000000-0000-0000-0000-000000000000")
DEFAULT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")

SessionMaker = async_sessionmaker[AsyncSession]


# --------------------------------------------------------------------------- seed helpers


async def _seed_job(
    session: AsyncSession,
    *,
    organization_id: UUID = DEFAULT_ORG_ID,
    status: JobStatus = JobStatus.IN_REVIEW,
) -> RedactionJob:
    document = Document(
        filename="doc.pdf",
        content_type="application/pdf",
        file_size=1024,
        organization_id=organization_id,
        storage_path="k",
        storage_url="k",
    )
    session.add(document)
    await session.flush()  # type: ignore[attr-defined]
    job = RedactionJob(document_id=document.id, organization_id=organization_id, status=status)
    session.add(job)
    await session.flush()  # type: ignore[attr-defined]
    return job


async def _seed_span(
    session: AsyncSession,
    job: RedactionJob,
    *,
    page_number: int = 1,
    text: str = "John Doe",
    bboxes: list[object] | None = None,
) -> Span:
    page = Page(document_id=job.document_id, page_number=page_number)
    session.add(page)
    await session.flush()  # type: ignore[attr-defined]
    span = Span(
        page_id=page.id,
        bboxes=[[1.0, 2.0, 3.0, 4.0]] if bboxes is None else bboxes,
        text=text,
        category="PERSON",
        source_tier=SourceTier.TIER_1,
        confidence=0.9,
    )
    session.add(span)
    await session.flush()  # type: ignore[attr-defined]
    return span


async def _seed_disposition(
    session: AsyncSession,
    span: Span,
    action: DispositionAction,
) -> Disposition:
    disposition = Disposition(span_id=span.id, action=action, reviewer_id=DEFAULT_USER_ID)
    session.add(disposition)
    await session.flush()  # type: ignore[attr-defined]
    return disposition


async def _seed_member_user(session: AsyncSession) -> User:
    user = User(name="Member", email=f"member-{uuid4()}@example.com")
    session.add(user)
    await session.flush()  # type: ignore[attr-defined]
    session.add(Membership(user_id=user.id, organization_id=DEFAULT_ORG_ID, role=MembershipRole.MEMBER))
    await session.commit()
    return user


# --------------------------------------------------------------------------- assert helpers


async def _count(session_maker: SessionMaker, model: type, **filters: object) -> int:
    stmt = select(func.count()).select_from(model)
    for column, value in filters.items():
        stmt = stmt.where(getattr(model, column) == value)
    async with session_maker() as check:
        return (await check.execute(stmt)).scalar_one()


async def _fetch_job(session_maker: SessionMaker, job_id: UUID) -> RedactionJob:
    async with session_maker() as check:
        return (await check.execute(select(RedactionJob).where(RedactionJob.id == job_id))).scalar_one()


def _member_headers(user_id: UUID) -> dict[str, str]:
    return {"X-Test-User-ID": str(user_id), "X-Test-Org-ID": str(DEFAULT_ORG_ID)}


# --------------------------------------------------------------------------- create


class TestCreateJob:
    @pytest.mark.asyncio
    async def test_upload_creates_in_review_job(
        self, client: AsyncClient, fake_storage_client: FakeStorageClient
    ) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=1)

        response = await client.post("/jobs", files={"file": ("doc.pdf", pdf_bytes, "application/pdf")})

        assert response.status_code == HTTPStatus.CREATED
        body = response.json()
        assert body["status"] == JobStatus.IN_REVIEW.value
        document_id = UUID(body["document_id"])
        assert keys.original_pdf_key(document_id) in fake_storage_client.uploads

    @pytest.mark.asyncio
    async def test_rejects_non_pdf(self, client: AsyncClient) -> None:
        response = await client.post("/jobs", files={"file": ("doc.txt", b"hello", "text/plain")})
        assert response.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    @pytest.mark.asyncio
    async def test_rejects_encrypted_pdf(self, client: AsyncClient) -> None:
        response = await client.post("/jobs", files={"file": ("e.pdf", build_encrypted_pdf(), "application/pdf")})
        assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_rejects_malformed_pdf(self, client: AsyncClient) -> None:
        response = await client.post("/jobs", files={"file": ("m.pdf", build_malformed_pdf(), "application/pdf")})
        assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_rejects_image_only_page(self, client: AsyncClient) -> None:
        pdf_bytes = build_mixed_native_and_image_pdf(native_pages=1, image_pages=(2,))
        response = await client.post("/jobs", files={"file": ("i.pdf", pdf_bytes, "application/pdf")})
        assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_oversized_upload_rejected_413(self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("redact_api.core.config.settings.max_file_size_bytes", 10)
        pdf_bytes = build_multi_page_pdf(page_count=1)
        assert len(pdf_bytes) > 10

        response = await client.post("/jobs", files={"file": ("big.pdf", pdf_bytes, "application/pdf")})
        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE


# --------------------------------------------------------------------------- get / spans


class TestGetJob:
    @pytest.mark.asyncio
    async def test_get_returns_job(self, client: AsyncClient, session: AsyncSession) -> None:
        job = await _seed_job(session)
        await session.commit()

        response = await client.get(f"/jobs/{job.id}")
        assert response.status_code == HTTPStatus.OK
        assert response.json()["id"] == str(job.id)

    @pytest.mark.asyncio
    async def test_missing_job_404(self, client: AsyncClient) -> None:
        response = await client.get(f"/jobs/{uuid4()}")
        assert response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_tenant_isolation_404(self, client: AsyncClient, session: AsyncSession) -> None:
        other_org = Organization(name=f"Other {uuid4()}")
        session.add(other_org)
        await session.flush()  # type: ignore[attr-defined]
        job = await _seed_job(session, organization_id=other_org.id)
        await session.commit()

        response = await client.get(f"/jobs/{job.id}")
        assert response.status_code == HTTPStatus.NOT_FOUND


class TestListSpans:
    @pytest.mark.asyncio
    async def test_lists_spans_ordered_by_page(self, client: AsyncClient, session: AsyncSession) -> None:
        job = await _seed_job(session)
        await _seed_span(session, job, page_number=2, text="second")
        await _seed_span(session, job, page_number=1, text="first")
        await session.commit()

        response = await client.get(f"/jobs/{job.id}/spans")
        assert response.status_code == HTTPStatus.OK
        texts = [span["text"] for span in response.json()]
        assert texts == ["first", "second"]

    @pytest.mark.asyncio
    async def test_empty_when_no_spans(self, client: AsyncClient, session: AsyncSession) -> None:
        job = await _seed_job(session)
        await session.commit()

        response = await client.get(f"/jobs/{job.id}/spans")
        assert response.status_code == HTTPStatus.OK
        assert response.json() == []


# --------------------------------------------------------------------------- dispositions


class TestDispositions:
    @pytest.mark.asyncio
    async def test_approve_and_reject_batch(
        self, client: AsyncClient, session: AsyncSession, session_maker: SessionMaker
    ) -> None:
        job = await _seed_job(session)
        span_a = await _seed_span(session, job, page_number=1)
        span_b = await _seed_span(session, job, page_number=2)
        await session.commit()

        response = await client.post(
            f"/jobs/{job.id}/dispositions",
            json={
                "items": [
                    {"verb": "approve", "span_id": str(span_a.id)},
                    {"verb": "reject", "span_id": str(span_b.id)},
                ]
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"applied": 2, "skipped": 0, "spans_created": 0}
        assert await _count(session_maker, Disposition) == 2
        assert await _count(session_maker, AuditEntry, job_id=job.id) == 2

    @pytest.mark.asyncio
    async def test_idempotent_resubmission_skips(
        self, client: AsyncClient, session: AsyncSession, session_maker: SessionMaker
    ) -> None:
        job = await _seed_job(session)
        span = await _seed_span(session, job)
        await session.commit()

        first = await client.post(
            f"/jobs/{job.id}/dispositions",
            json={"items": [{"verb": "approve", "span_id": str(span.id)}]},
        )
        assert first.json()["applied"] == 1

        second = await client.post(
            f"/jobs/{job.id}/dispositions",
            json={"items": [{"verb": "approve", "span_id": str(span.id)}]},
        )
        assert second.json() == {"applied": 0, "skipped": 1, "spans_created": 0}
        assert await _count(session_maker, Disposition, span_id=span.id) == 1
        assert await _count(session_maker, AuditEntry, job_id=job.id) == 1

    @pytest.mark.asyncio
    async def test_redisposition_updates_in_place(
        self, client: AsyncClient, session: AsyncSession, session_maker: SessionMaker
    ) -> None:
        job = await _seed_job(session)
        span = await _seed_span(session, job)
        await session.commit()

        await client.post(
            f"/jobs/{job.id}/dispositions",
            json={"items": [{"verb": "approve", "span_id": str(span.id)}]},
        )
        response = await client.post(
            f"/jobs/{job.id}/dispositions",
            json={"items": [{"verb": "reject", "span_id": str(span.id)}]},
        )
        assert response.json()["applied"] == 1

        assert await _count(session_maker, Disposition, span_id=span.id) == 1
        async with session_maker() as check:
            disposition = (
                await check.execute(select(Disposition).where(Disposition.span_id == span.id))
            ).scalar_one()
            assert disposition.action == DispositionAction.REJECTED
        assert await _count(session_maker, AuditEntry, job_id=job.id) == 2

    @pytest.mark.asyncio
    async def test_edit_updates_span_text(
        self, client: AsyncClient, session: AsyncSession, session_maker: SessionMaker
    ) -> None:
        job = await _seed_job(session)
        span = await _seed_span(session, job, text="original")
        await session.commit()

        response = await client.post(
            f"/jobs/{job.id}/dispositions",
            json={"items": [{"verb": "edit", "span_id": str(span.id), "text": "corrected"}]},
        )
        assert response.json()["applied"] == 1

        async with session_maker() as check:
            refreshed = (await check.execute(select(Span).where(Span.id == span.id))).scalar_one()
            assert refreshed.text == "corrected"

    @pytest.mark.asyncio
    async def test_add_manual_span(
        self, client: AsyncClient, session: AsyncSession, session_maker: SessionMaker
    ) -> None:
        job = await _seed_job(session)
        await session.commit()

        response = await client.post(
            f"/jobs/{job.id}/dispositions",
            json={
                "items": [
                    {
                        "verb": "add_manual_span",
                        "page_number": 1,
                        "bboxes": [[1.0, 2.0, 3.0, 4.0]],
                        "text": "manual pii",
                        "category": "PERSON",
                    }
                ]
            },
        )
        assert response.json() == {"applied": 1, "skipped": 0, "spans_created": 1}

        async with session_maker() as check:
            span = (
                await check.execute(
                    select(Span).join(Page, Span.page_id == Page.id).where(Page.document_id == job.document_id)
                )
            ).scalar_one()
            assert span.source_tier == SourceTier.MANUAL
        assert await _count(session_maker, Disposition, span_id=span.id) == 1

    @pytest.mark.asyncio
    async def test_rejects_client_supplied_reviewer_id(self, client: AsyncClient, session: AsyncSession) -> None:
        job = await _seed_job(session)
        span = await _seed_span(session, job)
        await session.commit()

        response = await client.post(
            f"/jobs/{job.id}/dispositions",
            json={"items": [{"verb": "approve", "span_id": str(span.id), "reviewer_id": str(uuid4())}]},
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_conflict_when_past_in_review(self, client: AsyncClient, session: AsyncSession) -> None:
        job = await _seed_job(session, status=JobStatus.VERIFIED)
        span = await _seed_span(session, job)
        await session.commit()

        response = await client.post(
            f"/jobs/{job.id}/dispositions",
            json={"items": [{"verb": "approve", "span_id": str(span.id)}]},
        )
        assert response.status_code == HTTPStatus.CONFLICT

    @pytest.mark.asyncio
    async def test_unknown_span_404(self, client: AsyncClient, session: AsyncSession) -> None:
        job = await _seed_job(session)
        await session.commit()

        response = await client.post(
            f"/jobs/{job.id}/dispositions",
            json={"items": [{"verb": "approve", "span_id": str(uuid4())}]},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND


# --------------------------------------------------------------------------- apply


class TestApply:
    @pytest.mark.asyncio
    async def test_apply_zero_spans_verifies(
        self, client: AsyncClient, session: AsyncSession, fake_storage_client: FakeStorageClient
    ) -> None:
        job = await _seed_job(session)
        await session.commit()
        fake_storage_client.uploads[keys.original_pdf_key(job.document_id)] = build_multi_page_pdf(page_count=1)

        response = await client.post(f"/jobs/{job.id}/apply")
        assert response.status_code == HTTPStatus.OK
        assert response.json()["status"] == JobStatus.VERIFIED.value
        assert keys.redacted_pdf_key(job.id) in fake_storage_client.uploads

    @pytest.mark.asyncio
    async def test_apply_rejected_span_verifies(
        self, client: AsyncClient, session: AsyncSession, fake_storage_client: FakeStorageClient
    ) -> None:
        job = await _seed_job(session)
        span = await _seed_span(session, job)
        await _seed_disposition(session, span, DispositionAction.REJECTED)
        await session.commit()
        fake_storage_client.uploads[keys.original_pdf_key(job.document_id)] = build_multi_page_pdf(page_count=1)

        response = await client.post(f"/jobs/{job.id}/apply")
        assert response.status_code == HTTPStatus.OK
        assert response.json()["status"] == JobStatus.VERIFIED.value
        assert keys.redacted_pdf_key(job.id) in fake_storage_client.uploads

    @pytest.mark.asyncio
    async def test_apply_only_projects_approved_spans(
        self,
        client: AsyncClient,
        session: AsyncSession,
        fake_storage_client: FakeStorageClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """R5 safety invariant: a REJECTED span must never reach ``apply()``'s burn set."""
        job = await _seed_job(session)
        approved_span = await _seed_span(session, job, page_number=1, text="approved-pii")
        rejected_span = await _seed_span(session, job, page_number=2, text="rejected-pii")
        await _seed_disposition(session, approved_span, DispositionAction.APPROVED)
        await _seed_disposition(session, rejected_span, DispositionAction.REJECTED)
        await session.commit()
        fake_storage_client.uploads[keys.original_pdf_key(job.document_id)] = build_multi_page_pdf(page_count=1)

        captured_spans: list[ApprovedSpan] = []

        def _capturing_apply(_pdf_bytes: bytes, spans: list[ApprovedSpan]) -> ApplyResult:
            captured_spans.extend(spans)
            verify_result = VerifyResult(verdict=VerifyVerdict.PASS, checks=[], findings=[])
            return ApplyResult(pdf_bytes=b"redacted", verify_result=verify_result)

        monkeypatch.setattr("redact_api.api.jobs.apply", _capturing_apply)

        response = await client.post(f"/jobs/{job.id}/apply")
        assert response.status_code == HTTPStatus.OK
        assert [span.text for span in captured_spans] == ["approved-pii"]

    @pytest.mark.asyncio
    async def test_apply_tenant_isolation_404(self, client: AsyncClient, session: AsyncSession) -> None:
        other_org = Organization(name=f"Other {uuid4()}")
        session.add(other_org)
        await session.flush()  # type: ignore[attr-defined]
        job = await _seed_job(session, organization_id=other_org.id)
        await session.commit()

        response = await client.post(f"/jobs/{job.id}/apply")
        assert response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_apply_undispositioned_spans_409(
        self, client: AsyncClient, session: AsyncSession, fake_storage_client: FakeStorageClient
    ) -> None:
        job = await _seed_job(session)
        await _seed_span(session, job)
        await session.commit()
        fake_storage_client.uploads[keys.original_pdf_key(job.document_id)] = build_multi_page_pdf(page_count=1)

        response = await client.post(f"/jobs/{job.id}/apply")
        assert response.status_code == HTTPStatus.CONFLICT

    @pytest.mark.asyncio
    async def test_apply_wrong_state_409(self, client: AsyncClient, session: AsyncSession) -> None:
        job = await _seed_job(session, status=JobStatus.UPLOADED)
        await session.commit()

        response = await client.post(f"/jobs/{job.id}/apply")
        assert response.status_code == HTTPStatus.CONFLICT

    @pytest.mark.asyncio
    async def test_apply_malformed_bbox_422(
        self,
        client: AsyncClient,
        session: AsyncSession,
        session_maker: SessionMaker,
        fake_storage_client: FakeStorageClient,
    ) -> None:
        job = await _seed_job(session)
        span = await _seed_span(session, job, bboxes=[[1.0, 2.0, 3.0]])
        await _seed_disposition(session, span, DispositionAction.APPROVED)
        await session.commit()
        fake_storage_client.uploads[keys.original_pdf_key(job.document_id)] = build_multi_page_pdf(page_count=1)

        response = await client.post(f"/jobs/{job.id}/apply")
        assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT

        refreshed = await _fetch_job(session_maker, job.id)
        assert refreshed.status == JobStatus.IN_REVIEW

    @pytest.mark.asyncio
    async def test_apply_verify_fail_422_marks_failed(
        self,
        client: AsyncClient,
        session: AsyncSession,
        session_maker: SessionMaker,
        fake_storage_client: FakeStorageClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        job = await _seed_job(session)
        span = await _seed_span(session, job)
        await _seed_disposition(session, span, DispositionAction.APPROVED)
        await session.commit()
        pdf_bytes, _ref = make_pii_source_pdf()
        fake_storage_client.uploads[keys.original_pdf_key(job.document_id)] = pdf_bytes

        def _failing_apply(_pdf_bytes: bytes, _spans: list[ApprovedSpan]) -> ApplyResult:
            verify_result = VerifyResult(
                verdict=VerifyVerdict.FAIL,
                checks=[CheckSummary(check_type=CheckType.TEXT_LAYER, passed=False, pages_checked=1)],
                findings=[
                    VerifyFinding(redacted_string_digest="deadbeef", check_type=CheckType.TEXT_LAYER, page_number=1)
                ],
            )
            return ApplyResult(pdf_bytes=b"redacted", verify_result=verify_result)

        monkeypatch.setattr("redact_api.api.jobs.apply", _failing_apply)

        response = await client.post(f"/jobs/{job.id}/apply")
        assert response.status_code == HTTPStatus.UNPROCESSABLE_CONTENT
        assert response.json()["detail"]["verdict"] == VerifyVerdict.FAIL.value

        refreshed = await _fetch_job(session_maker, job.id)
        assert refreshed.status == JobStatus.FAILED

    @pytest.mark.asyncio
    async def test_apply_member_forbidden(self, client: AsyncClient, session: AsyncSession) -> None:
        job = await _seed_job(session)
        member = await _seed_member_user(session)

        response = await client.post(f"/jobs/{job.id}/apply", headers=_member_headers(member.id))
        assert response.status_code == HTTPStatus.FORBIDDEN


# --------------------------------------------------------------------------- export


class TestExport:
    @staticmethod
    async def _seed_verified(session: AsyncSession, fake_storage_client: FakeStorageClient) -> RedactionJob:
        job = await _seed_job(session, status=JobStatus.VERIFIED)
        redacted_key = keys.redacted_pdf_key(job.id)
        job.redacted_pdf_key = redacted_key
        session.add(job)
        await session.commit()
        fake_storage_client.uploads[redacted_key] = b"%PDF-redacted"
        return job

    @pytest.mark.asyncio
    async def test_export_returns_pdf_and_transitions(
        self,
        client: AsyncClient,
        session: AsyncSession,
        session_maker: SessionMaker,
        fake_storage_client: FakeStorageClient,
    ) -> None:
        job = await self._seed_verified(session, fake_storage_client)

        response = await client.get(f"/jobs/{job.id}/export")
        assert response.status_code == HTTPStatus.OK
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == b"%PDF-redacted"

        refreshed = await _fetch_job(session_maker, job.id)
        assert refreshed.status == JobStatus.EXPORTED

    @pytest.mark.asyncio
    async def test_export_idempotent_reread(
        self,
        client: AsyncClient,
        session: AsyncSession,
        session_maker: SessionMaker,
        fake_storage_client: FakeStorageClient,
    ) -> None:
        job = await self._seed_verified(session, fake_storage_client)

        first = await client.get(f"/jobs/{job.id}/export")
        second = await client.get(f"/jobs/{job.id}/export")
        assert first.status_code == HTTPStatus.OK
        assert second.status_code == HTTPStatus.OK
        assert second.content == b"%PDF-redacted"

        # No re-transition and no duplicate side effect on the second call.
        refreshed = await _fetch_job(session_maker, job.id)
        assert refreshed.status == JobStatus.EXPORTED

    @pytest.mark.asyncio
    async def test_export_before_verified_409(self, client: AsyncClient, session: AsyncSession) -> None:
        job = await _seed_job(session, status=JobStatus.IN_REVIEW)
        await session.commit()

        response = await client.get(f"/jobs/{job.id}/export")
        assert response.status_code == HTTPStatus.CONFLICT

    @pytest.mark.asyncio
    async def test_export_member_forbidden(
        self, client: AsyncClient, session: AsyncSession, fake_storage_client: FakeStorageClient
    ) -> None:
        job = await self._seed_verified(session, fake_storage_client)
        member = await _seed_member_user(session)

        response = await client.get(f"/jobs/{job.id}/export", headers=_member_headers(member.id))
        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.asyncio
    async def test_export_tenant_isolation_404(self, client: AsyncClient, session: AsyncSession) -> None:
        other_org = Organization(name=f"Other {uuid4()}")
        session.add(other_org)
        await session.flush()  # type: ignore[attr-defined]
        job = await _seed_job(session, organization_id=other_org.id, status=JobStatus.VERIFIED)
        await session.commit()

        response = await client.get(f"/jobs/{job.id}/export")
        assert response.status_code == HTTPStatus.NOT_FOUND
