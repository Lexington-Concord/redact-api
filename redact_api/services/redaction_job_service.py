"""Service layer for the redaction-job state machine and audit hash chain.

Holds the two invariants that must not live in the API layer:

* ``transition_job_status`` enforces the allowed ``JobStatus`` edges (``VALID_TRANSITIONS``)
  and blocks the move to ``APPLYING`` until every span for the job has a disposition.
* ``append_audit_entry`` writes append-only, SHA-256 hash-chained audit rows that carry a
  digest of the *normalized* span text (via the redact-api#1 verify gate's ``normalize_text``)
  rather than any raw PII.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from redact_api.models.audit_entry import AuditAction, AuditEntry
from redact_api.models.disposition import Disposition
from redact_api.models.page import Page
from redact_api.models.redaction_job import JobStatus, RedactionJob
from redact_api.models.span import Span
from redact_api.redaction.verify_gate import normalize_text

# Genesis link for the first audit entry of a job (64 zero hex chars).
GENESIS_PREV_HASH = "0" * 64

# Category label for job-level lifecycle audit entries that are not tied to a PII span
# (APPLY_STARTED / EXPORTED). VERIFY_PASSED / VERIFY_FAILED instead JSON-encode a digest-only
# verdict blob into ``category`` -- see ``apply_job``.
JOB_LIFECYCLE_CATEGORY = "job_lifecycle"

# Allowed job-status transitions. The happy path is the linear detection->export chain;
# any non-terminal state may also fail. FAILED and EXPORTED are terminal (empty sets) --
# there is deliberately no retry edge in V1 (deviation from minutes-shared's pipeline).
VALID_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.UPLOADED: frozenset({JobStatus.INGESTED, JobStatus.FAILED}),
    JobStatus.INGESTED: frozenset({JobStatus.DETECTED, JobStatus.FAILED}),
    JobStatus.DETECTED: frozenset({JobStatus.IN_REVIEW, JobStatus.FAILED}),
    JobStatus.IN_REVIEW: frozenset({JobStatus.APPLYING, JobStatus.FAILED}),
    JobStatus.APPLYING: frozenset({JobStatus.VERIFIED, JobStatus.FAILED}),
    JobStatus.VERIFIED: frozenset({JobStatus.EXPORTED, JobStatus.FAILED}),
    JobStatus.EXPORTED: frozenset(),
    JobStatus.FAILED: frozenset(),
}


class InvalidStateTransitionError(Exception):
    """Raised when a requested job-status transition is not permitted."""


class UndispositionedSpansError(Exception):
    """Raised when a job is moved to APPLYING while spans still lack a disposition."""


@dataclass(frozen=True, kw_only=True)
class AuditEntryInput:
    """Caller-supplied content for an audit entry.

    ``text`` is the raw span text used only to compute the stored digest; it is never
    persisted. It is ``None`` for job-level lifecycle events (APPLY_STARTED / VERIFY_* /
    EXPORTED), which carry no span text -- those entries persist a NULL ``text_hash``.
    ``organization_id`` is intentionally absent -- it is sourced from the job.
    """

    action: AuditAction
    category: str
    text: str | None
    reviewer_id: UUID
    span_id: UUID | None = None


def _hash_hex(value: str) -> str:
    """Return the SHA-256 hex digest of ``value``."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compute_entry_hash(prev_hash: str, payload: dict[str, str | None]) -> str:
    """Chain hash: SHA-256 of ``prev_hash`` concatenated with the canonical JSON payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return _hash_hex(prev_hash + canonical)


class _ChainPayloadSource(Protocol):
    """Structural shape shared by ``AuditEntryInput`` and ``AuditEntry`` for payload building.

    Declared via read-only properties so both a frozen dataclass (``AuditEntryInput``) and a
    SQLModel table row (``AuditEntry``) satisfy it structurally -- only reading these fields.
    """

    @property
    def action(self) -> AuditAction: ...
    @property
    def category(self) -> str: ...
    @property
    def reviewer_id(self) -> UUID: ...
    @property
    def span_id(self) -> UUID | None: ...


def _chain_payload(source: _ChainPayloadSource, *, job_id: UUID, created_at: datetime) -> dict[str, str | None]:
    """Build the pinned 6-key hashed payload (resolution #6) -- do not add or remove keys.

    Single source of truth for both the write path (``append_audit_entry``, building from a
    caller-supplied ``AuditEntryInput``) and the read path (``verify_audit_chain``, rebuilding
    from a persisted ``AuditEntry`` row), so the two can never silently drift apart. ``source``
    accepts either shape structurally -- both expose action/category/reviewer_id/span_id.
    """
    return {
        "job_id": str(job_id),
        "span_id": str(source.span_id) if source.span_id is not None else None,
        "action": source.action.value,
        "category": source.category,
        "reviewer": str(source.reviewer_id),
        "created_at": created_at.isoformat(),
    }


async def _count_undispositioned_spans(session: AsyncSession, document_id: UUID) -> int:
    """Count spans on the job's document that have no disposition."""
    stmt = (
        select(func.count())
        .select_from(Span)
        .join(Page, col(Span.page_id) == col(Page.id))
        .outerjoin(Disposition, col(Disposition.span_id) == col(Span.id))
        .where(col(Page.document_id) == document_id)
        .where(col(Disposition.id).is_(None))
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def transition_job_status(
    session: AsyncSession,
    job: RedactionJob,
    new_status: JobStatus,
) -> RedactionJob:
    """Move ``job`` to ``new_status`` if the transition is allowed.

    Raises ``InvalidStateTransitionError`` for a disallowed edge and, for the move to
    ``APPLYING``, ``UndispositionedSpansError`` if any span still lacks a disposition. Both
    checks run before ``job.status`` is mutated, so a rejected transition leaves it unchanged.
    """
    if new_status not in VALID_TRANSITIONS[job.status]:
        msg = f"Cannot transition job {job.id} from {job.status.value} to {new_status.value}"
        raise InvalidStateTransitionError(msg)

    if new_status is JobStatus.APPLYING:
        undispositioned = await _count_undispositioned_spans(session, job.document_id)
        if undispositioned:
            msg = f"Job {job.id} has {undispositioned} undispositioned span(s); cannot move to APPLYING"
            raise UndispositionedSpansError(msg)

    job.status = new_status
    session.add(job)
    await session.flush()  # type: ignore[attr-defined]
    return job


async def _next_chain_link(session: AsyncSession, job_id: UUID) -> tuple[str, int]:
    """Return ``(prev_hash, sequence)`` for the next audit entry of ``job_id``."""
    stmt = (
        select(AuditEntry).where(col(AuditEntry.job_id) == job_id).order_by(col(AuditEntry.sequence).desc()).limit(1)
    )
    result = await session.execute(stmt)
    last = result.scalars().first()
    if last is None:
        return GENESIS_PREV_HASH, 1
    return last.entry_hash, last.sequence + 1


async def append_audit_entry(
    session: AsyncSession,
    job_id: UUID,
    event: AuditEntryInput,
) -> AuditEntry:
    """Append a hash-chained audit entry for ``job_id``.

    The entry stores a digest of the normalized ``event.text`` (never the raw text) and derives
    its ``organization_id`` from the loaded job, so a caller cannot mis-scope the row.
    ``created_at`` is fixed in Python before insert because its ISO value is part of the hashed
    payload.
    """
    result = await session.execute(select(RedactionJob).where(col(RedactionJob.id) == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        msg = f"RedactionJob {job_id} not found"
        raise LookupError(msg)

    if event.span_id is not None and event.text is None:
        no_text_msg = "A span-level audit entry (span_id set) must carry text to hash; got text=None"
        raise ValueError(no_text_msg)

    prev_hash, sequence = await _next_chain_link(session, job_id)
    # Job-level lifecycle events carry no span text, so they store a NULL digest. text_hash
    # was never part of the pinned hashed payload, so this branch does not perturb the chain.
    text_hash = _hash_hex(normalize_text(event.text)) if event.text is not None else None
    # Why: every other TimestampedTable column relies on the DB's server_default=now()
    # for created_at, but here the exact persisted value must also be hashed into the
    # payload below -- so it's generated in Python and passed through explicitly instead.
    created_at = datetime.now(UTC)
    # text_hash is stored on the row but deliberately excluded from the hashed payload.
    payload = _chain_payload(event, job_id=job_id, created_at=created_at)
    entry_hash = compute_entry_hash(prev_hash, payload)

    entry = AuditEntry(
        job_id=job_id,
        span_id=event.span_id,
        reviewer_id=event.reviewer_id,
        organization_id=job.organization_id,
        action=event.action,
        category=event.category,
        text_hash=text_hash,
        entry_hash=entry_hash,
        prev_hash=prev_hash,
        sequence=sequence,
        created_at=created_at,
    )
    session.add(entry)
    await session.flush()  # type: ignore[attr-defined]
    return entry


def _entry_payload(entry: AuditEntry) -> dict[str, str | None]:
    """Rebuild the pinned 6-key hashed payload for a persisted ``entry`` via ``_chain_payload``."""
    return _chain_payload(entry, job_id=entry.job_id, created_at=entry.created_at)


@dataclass(frozen=True, kw_only=True)
class ChainVerifyResult:
    """Outcome of recomputing a job's audit hash chain.

    ``head`` is the ``entry_hash`` of the last entry by sequence at verification time, or
    ``GENESIS_PREV_HASH`` for an empty chain. ``first_broken_entry_id`` is the id of the first
    entry whose stored ``prev_hash``/``entry_hash`` disagrees with the recomputed chain, or
    ``None`` when the chain is intact.
    """

    verified: bool
    entry_count: int
    head: str
    first_broken_entry_id: UUID | None = None


async def verify_audit_chain(session: AsyncSession, job_id: UUID) -> ChainVerifyResult:
    """Recompute ``job_id``'s audit hash chain and report whether it is intact.

    Walks the entries in ``sequence`` order, recomputing each ``entry_hash`` from the pinned
    6-key payload (``compute_entry_hash``) and confirming each ``prev_hash`` links to the prior
    recomputed hash. An empty chain is vacuously verified.
    """
    stmt = select(AuditEntry).where(col(AuditEntry.job_id) == job_id).order_by(col(AuditEntry.sequence))
    entries = list((await session.execute(stmt)).scalars().all())

    prev = GENESIS_PREV_HASH
    first_broken: UUID | None = None
    for entry in entries:
        expected = compute_entry_hash(prev, _entry_payload(entry))
        if entry.prev_hash != prev or entry.entry_hash != expected:
            first_broken = entry.id
            break
        prev = entry.entry_hash

    head = entries[-1].entry_hash if entries else GENESIS_PREV_HASH
    return ChainVerifyResult(
        verified=first_broken is None,
        entry_count=len(entries),
        head=head,
        first_broken_entry_id=first_broken,
    )
