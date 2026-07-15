"""Typed public contract for the export manifest bundled with a redacted job (redact-api#9).

The manifest is a self-contained, digest-only record of a job's full audit trail, assembled
fresh at export time from the live hash chain and shipped inside the export zip beside
``redacted.pdf``. Like ``AuditEntry`` it carries only category labels and SHA-256 digests --
never raw span text -- so it can be stored or forwarded without re-leaking redacted PII.

This is a pure Pydantic contract module: it has zero database, session, or storage imports,
mirroring ``redact_api.redaction.models``. Assembly (downloading/hashing PDF bytes, querying
the chain) lives in ``redact_api.services.export_manifest_service``.

V1 scope (R9): No retention policy and no cryptographic signing in V1 -- the hash chain
provides tamper-EVIDENCE only, not tamper-proofness or non-repudiation.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from redact_api.models.audit_entry import AuditAction


class ManifestDisposition(BaseModel):
    """One span-level audit row (``span_id IS NOT NULL``): a reviewer disposition of a span.

    ``text_hash`` is the SHA-256 digest of the normalized span text (never the text itself);
    it may be ``None`` only in the degenerate case of a span-level row appended without text.
    """

    span_id: UUID
    action: AuditAction
    category: str
    text_hash: str | None
    reviewer_id: UUID
    sequence: int
    created_at: datetime


class ManifestLifecycleEvent(BaseModel):
    """One job-level audit row (``span_id IS NULL``): a pipeline lifecycle event.

    Covers APPLY_STARTED / VERIFY_PASSED / VERIFY_FAILED / EXPORTED. The in-progress export's
    own EXPORTED row is legitimately absent from its own manifest -- it is appended only after
    manifest assembly succeeds, so a first-export manifest never lists its own EXPORTED event.
    """

    action: AuditAction
    reviewer_id: UUID
    created_at: datetime


class ExportManifest(BaseModel):
    """Self-contained, digest-only proof of a redacted job's provenance and audit trail.

    ``audit_chain_verified`` is always ``True`` for any manifest actually returned to a client
    (export 409s before assembly on a broken chain), but it is recorded explicitly so a
    standalone reader of the manifest JSON does not have to trust "no 409 was raised" as an
    implicit signal. ``generated_at`` is the UTC timestamp of manifest assembly itself -- not of
    the job's VERIFIED transition or of any individual audit entry.

    V1 scope (R9): No retention policy and no cryptographic signing in V1 -- the hash chain
    provides tamper-EVIDENCE only, not tamper-proofness or non-repudiation.
    """

    job_id: UUID
    document_id: UUID
    original_sha256: str
    redacted_sha256: str
    dispositions: list[ManifestDisposition]
    lifecycle_events: list[ManifestLifecycleEvent]
    verify_summary: dict[str, object]
    entry_count: int
    audit_chain_head: str
    audit_chain_verified: bool
    generated_at: datetime
