"""Assembly of the export manifest for a redacted job (redact-api#9).

``assemble_export_manifest`` is the single place that turns a VERIFIED job's live audit hash
chain plus its stored original/redacted PDFs into the typed ``ExportManifest`` contract. It
verifies the chain first (raising ``ExportChainBrokenError`` before any PDF bytes are touched),
hashes both PDFs, splits the audit rows into span-level dispositions vs. job-level lifecycle
events, and decodes the digest-only verify verdict blob. Assembly is stateless and read-only:
it persists nothing and is safe to re-run on every export GET, always reflecting current chain
state rather than a cached snapshot.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from redact_api.manifest.models import (
    ExportManifest,
    ManifestDisposition,
    ManifestLifecycleEvent,
)
from redact_api.models.audit_entry import AuditAction, AuditEntry
from redact_api.models.redaction_job import RedactionJob
from redact_api.services.redaction_job_service import verify_audit_chain
from redact_api.storage import keys
from redact_api.storage.client import StorageClient

_VERIFY_ACTIONS = (AuditAction.VERIFY_PASSED, AuditAction.VERIFY_FAILED)


class ExportChainBrokenError(Exception):
    """Raised when a job's audit hash chain fails verification at manifest-assembly time."""


def _sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


async def assemble_export_manifest(
    session: AsyncSession,
    storage: StorageClient,
    job: RedactionJob,
) -> ExportManifest:
    """Assemble the ``ExportManifest`` for ``job`` from its live audit chain and stored PDFs.

    Verifies the audit chain first and raises ``ExportChainBrokenError`` before any PDF bytes
    are downloaded if it is broken. Requires ``job.redacted_pdf_key`` to be set (the export
    endpoint guarantees this for a VERIFIED/EXPORTED job).
    """
    chain = await verify_audit_chain(session, job.id)
    if not chain.verified:
        msg = f"Audit chain for job {job.id} failed verification (first broken: {chain.first_broken_entry_id})"
        raise ExportChainBrokenError(msg)

    if job.redacted_pdf_key is None:
        msg = f"Job {job.id} has no redacted artifact; cannot assemble an export manifest"
        raise ExportChainBrokenError(msg)

    original_bytes = await storage.download_bytes(keys.original_pdf_key(job.document_id))
    redacted_bytes = await storage.download_bytes(job.redacted_pdf_key)

    stmt = select(AuditEntry).where(col(AuditEntry.job_id) == job.id).order_by(col(AuditEntry.sequence))
    entries = list((await session.execute(stmt)).scalars().all())

    dispositions: list[ManifestDisposition] = []
    lifecycle_events: list[ManifestLifecycleEvent] = []
    verify_summary: dict[str, object] = {}
    for entry in entries:
        if entry.span_id is not None:
            dispositions.append(
                ManifestDisposition(
                    span_id=entry.span_id,
                    action=entry.action,
                    category=entry.category,
                    text_hash=entry.text_hash,
                    reviewer_id=entry.reviewer_id,
                    sequence=entry.sequence,
                    created_at=entry.created_at,
                )
            )
        else:
            lifecycle_events.append(
                ManifestLifecycleEvent(
                    action=entry.action,
                    reviewer_id=entry.reviewer_id,
                    created_at=entry.created_at,
                )
            )
        if not verify_summary and entry.action in _VERIFY_ACTIONS:
            verify_summary = json.loads(entry.category)

    return ExportManifest(
        job_id=job.id,
        document_id=job.document_id,
        original_sha256=_sha256_hex(original_bytes),
        redacted_sha256=_sha256_hex(redacted_bytes),
        dispositions=dispositions,
        lifecycle_events=lifecycle_events,
        verify_summary=verify_summary,
        entry_count=chain.entry_count,
        audit_chain_head=chain.head,
        audit_chain_verified=chain.verified,
        generated_at=datetime.now(UTC),
    )
