"""Integration tests for the export-manifest service (redact-api#9).

Drives ``assemble_export_manifest`` against a real DB (via ``seed_verified_job``) and an
in-memory storage double: correct PDF digests, disposition content/order, the parsed
verify-summary shape, chain head/entry-count/verified flags, the split of span-level rows
into ``dispositions`` vs. job-level rows into ``lifecycle_events``, the absence of the
in-progress job's own (not-yet-appended) EXPORTED row, and the broken-chain failure.
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from redact_api.models.audit_entry import AuditAction, AuditEntry
from redact_api.services.export_manifest_service import (
    ExportAssemblyError,
    assemble_export_manifest,
)
from redact_api.tests.conftest import FakeStorageClient
from redact_api.tests.integration.conftest import (
    SEED_ORIGINAL_PDF_BYTES,
    SEED_REDACTED_PDF_BYTES,
    SEED_VERIFY_SUMMARY,
    SeedVerifiedJob,
)


class TestAssembleExportManifest:
    @pytest.mark.asyncio
    async def test_hashes_match_stored_pdf_bytes(
        self,
        seed_verified_job: SeedVerifiedJob,
        session: AsyncSession,
    ) -> None:
        storage = FakeStorageClient()
        job = await seed_verified_job(storage)

        manifest = await assemble_export_manifest(session, storage, job)

        assert manifest.job_id == job.id
        assert manifest.document_id == job.document_id
        assert manifest.original_sha256 == hashlib.sha256(SEED_ORIGINAL_PDF_BYTES).hexdigest()
        assert manifest.redacted_sha256 == hashlib.sha256(SEED_REDACTED_PDF_BYTES).hexdigest()

    @pytest.mark.asyncio
    async def test_dispositions_hold_span_level_rows_in_order(
        self,
        seed_verified_job: SeedVerifiedJob,
        session: AsyncSession,
    ) -> None:
        storage = FakeStorageClient()
        job = await seed_verified_job(storage)

        manifest = await assemble_export_manifest(session, storage, job)

        assert len(manifest.dispositions) == 1
        disposition = manifest.dispositions[0]
        assert disposition.action == AuditAction.APPROVED
        assert disposition.category == "PERSON"
        assert disposition.text_digest is not None
        assert disposition.span_id is not None

    @pytest.mark.asyncio
    async def test_lifecycle_events_hold_job_level_rows_in_order(
        self,
        seed_verified_job: SeedVerifiedJob,
        session: AsyncSession,
    ) -> None:
        storage = FakeStorageClient()
        job = await seed_verified_job(storage)

        manifest = await assemble_export_manifest(session, storage, job)

        actions = [event.action for event in manifest.lifecycle_events]
        assert actions == [AuditAction.APPLY_STARTED, AuditAction.VERIFY_PASSED]

    @pytest.mark.asyncio
    async def test_in_progress_export_own_exported_row_absent(
        self,
        seed_verified_job: SeedVerifiedJob,
        session: AsyncSession,
    ) -> None:
        storage = FakeStorageClient()
        job = await seed_verified_job(storage)

        manifest = await assemble_export_manifest(session, storage, job)

        assert AuditAction.EXPORTED not in [event.action for event in manifest.lifecycle_events]

    @pytest.mark.asyncio
    async def test_verify_summary_parsed_to_exact_shape(
        self,
        seed_verified_job: SeedVerifiedJob,
        session: AsyncSession,
    ) -> None:
        storage = FakeStorageClient()
        job = await seed_verified_job(storage)

        manifest = await assemble_export_manifest(session, storage, job)

        assert manifest.verify_summary == SEED_VERIFY_SUMMARY

    @pytest.mark.asyncio
    async def test_chain_head_entry_count_and_verified(
        self,
        seed_verified_job: SeedVerifiedJob,
        session: AsyncSession,
    ) -> None:
        storage = FakeStorageClient()
        job = await seed_verified_job(storage)

        manifest = await assemble_export_manifest(session, storage, job)

        # Three seeded entries: span-level APPROVED + APPLY_STARTED + VERIFY_PASSED.
        assert manifest.entry_count == 3
        assert manifest.audit_chain_verified is True
        head = (
            await session.execute(
                select(AuditEntry.entry_hash)
                .where(AuditEntry.job_id == job.id)
                .order_by(col(AuditEntry.sequence).desc())
                .limit(1)
            )
        ).scalar_one()
        assert manifest.audit_chain_head == head

    @pytest.mark.asyncio
    async def test_broken_chain_raises_typed_error(
        self,
        seed_verified_job: SeedVerifiedJob,
        session: AsyncSession,
    ) -> None:
        storage = FakeStorageClient()
        job = await seed_verified_job(storage)
        # Tamper with the first entry so the whole chain fails verification.
        first = (
            await session.execute(
                select(AuditEntry).where(AuditEntry.job_id == job.id).order_by(AuditEntry.sequence).limit(1)
            )
        ).scalar_one()
        first.entry_hash = "0" * 64
        session.add(first)
        await session.flush()  # type: ignore[attr-defined]

        with pytest.raises(ExportAssemblyError):
            await assemble_export_manifest(session, storage, job)
