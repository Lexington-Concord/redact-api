"""Assembly of the export manifest for a redacted job (redact-api#9).

``assemble_export_manifest`` is the single place that turns a VERIFIED job's live audit hash
chain plus its stored original/redacted PDFs into the typed ``ExportManifest`` contract. It
verifies the chain first (raising ``ExportAssemblyError`` before any PDF bytes are touched),
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
from redact_api.services.redaction_job_service import ChainVerifyResult, verify_audit_chain
from redact_api.storage import keys
from redact_api.storage.client import StorageClient

_VERIFY_ACTIONS = (AuditAction.VERIFY_PASSED, AuditAction.VERIFY_FAILED)


class ExportAssemblyError(Exception):
    """Raised when a job's manifest cannot be assembled: a broken audit chain (tamper-evidence
    failure) or a missing redacted artifact (routine precondition, not tampering). Callers that
    need to distinguish the two should inspect the message; both currently 409 identically at
    the export endpoint.
    """


def _sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


async def assemble_export_manifest(
    session: AsyncSession,
    storage: StorageClient,
    job: RedactionJob,
    *,
    chain: ChainVerifyResult | None = None,
    redacted_bytes: bytes | None = None,
) -> ExportManifest:
    """Assemble the ``ExportManifest`` for ``job`` from its live audit chain and stored PDFs.

    Verifies the audit chain first and raises ``ExportAssemblyError`` before any PDF bytes
    are downloaded if it is broken. Requires ``job.redacted_pdf_key`` to be set (the export
    endpoint guarantees this for a VERIFIED/EXPORTED job).

    ``chain`` and ``redacted_bytes`` let a caller that already verified the chain / downloaded
    the redacted PDF for its own purposes (the export endpoint does both, to build the zip
    bundle) pass them through instead of this function repeating the same chain walk or
    object-storage fetch. Callers that don't have either on hand -- e.g. direct unit/integration
    tests -- omit both and this function computes them itself, exactly as before.
    """
    chain = chain if chain is not None else await verify_audit_chain(session, job.id)
    if not chain.verified:
        msg = f"Audit chain for job {job.id} failed verification (first broken: {chain.first_broken_entry_id})"
        raise ExportAssemblyError(msg)

    if job.redacted_pdf_key is None:
        msg = f"Job {job.id} has no redacted artifact; cannot assemble an export manifest"
        raise ExportAssemblyError(msg)

    original_bytes = await storage.download_bytes(keys.original_pdf_key(job.document_id))
    if redacted_bytes is None:
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
                    text_digest=entry.text_hash,
                    reviewer_id=entry.reviewer_id,
                    disposed_at=entry.created_at,
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
        # Why: takes the LAST matching entry rather than the first. There is at most one
        # verify-action entry per job today (no retry edge in VALID_TRANSITIONS -- APPLYING is
        # reachable only once per job lifecycle), but iterating to the last match keeps this
        # correct if that ever changes, rather than silently freezing on a stale verdict.
        if entry.action in _VERIFY_ACTIONS:
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
