"""Service layer for the job API surface (redact-api#7).

Two concerns live here, kept out of the router:

* **Projection** -- ``project_approved_spans`` reads the persisted span/disposition graph
  for a job's document and projects the *approved* spans into the pure ``ApprovedSpan``
  contract that ``redaction.apply`` consumes, coercing the untyped JSONB ``bboxes`` into
  the fixed ``(x0, y0, x1, y1)`` shape (a malformed shape raises ``ValidationError``,
  surfaced by the app's global handler as 422).
* **Disposition batch** -- ``apply_disposition_batch`` orchestrates the four reviewer
  verbs (approve / reject / edit / add-manual-span). Re-disposition updates the single
  unique-per-span ``Disposition`` row in place; an identical resubmission is a no-op that
  writes no new ``AuditEntry``. ``reviewer_id`` is always server-resolved by the caller
  (never client-supplied), so the request schemas forbid unknown fields.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from redact_api.models.audit_entry import AuditAction
from redact_api.models.disposition import Disposition, DispositionAction
from redact_api.models.page import Page
from redact_api.models.redaction_job import RedactionJob
from redact_api.models.span import SourceTier, Span
from redact_api.redaction.models import ApprovedSpan
from redact_api.services.redaction_job_service import AuditEntryInput, append_audit_entry

BBox = tuple[float, float, float, float]


class SpanNotFoundError(Exception):
    """Raised when a disposition item references a span not on the job's document."""


# ---------------------------------------------------------------------------
# Request/response schemas (the service owns the batch-input contract; the router
# imports these). ``extra="forbid"`` is the mechanism that rejects a client-supplied
# ``reviewer_id`` with 422 -- reviewer identity is always resolved from the tenant.
# ---------------------------------------------------------------------------


class _DispositionItemBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApproveItem(_DispositionItemBase):
    """Approve an existing span's redaction."""

    verb: Literal["approve"]
    span_id: UUID
    reason: str | None = None


class RejectItem(_DispositionItemBase):
    """Reject an existing span (it will not be burned in)."""

    verb: Literal["reject"]
    span_id: UUID
    reason: str | None = None


class EditItem(_DispositionItemBase):
    """Edit an existing span's text and/or bounding boxes, then approve it."""

    verb: Literal["edit"]
    span_id: UUID
    text: str
    bboxes: list[BBox] | None = None
    reason: str | None = None


class AddManualSpanItem(_DispositionItemBase):
    """Add a reviewer-authored manual span (approved on creation)."""

    verb: Literal["add_manual_span"]
    page_number: int = Field(ge=1)
    bboxes: list[BBox]
    text: str
    category: str
    reason: str | None = None


DispositionItem = Annotated[
    ApproveItem | RejectItem | EditItem | AddManualSpanItem,
    Field(discriminator="verb"),
]


class DispositionBatchRequest(BaseModel):
    """A batch of disposition verbs applied to one job in a single transaction."""

    model_config = ConfigDict(extra="forbid")

    items: list[DispositionItem] = Field(min_length=1)


class DispositionBatchResult(BaseModel):
    """Summary of a disposition batch: state-changing vs. idempotent-skipped counts."""

    applied: int
    skipped: int
    spans_created: int


# ---------------------------------------------------------------------------
# Verb -> action mappings
# ---------------------------------------------------------------------------

DISPOSITION_ACTION_BY_VERB: dict[str, DispositionAction] = {
    "approve": DispositionAction.APPROVED,
    "reject": DispositionAction.REJECTED,
    "edit": DispositionAction.APPROVED,
    "add_manual_span": DispositionAction.APPROVED,
}

AUDIT_ACTION_BY_VERB: dict[str, AuditAction] = {
    "approve": AuditAction.APPROVED,
    "reject": AuditAction.REJECTED,
    "edit": AuditAction.EDITED,
    "add_manual_span": AuditAction.MANUAL_SPAN_ADDED,
}


# ---------------------------------------------------------------------------
# Pure helpers (DB-free, unit-tested directly)
# ---------------------------------------------------------------------------


def build_approved_span(*, page_number: int, bboxes: list[Any], text: str) -> ApprovedSpan:
    """Coerce a persisted span's fields into an ``ApprovedSpan``.

    ``bboxes`` is the untyped JSONB ``list[Any]`` at rest; constructing ``ApprovedSpan``
    validates/coerces it into ``list[(x0, y0, x1, y1)]`` and raises ``ValidationError`` on
    a malformed shape (wrong arity, non-numeric, non-list element).
    """
    return ApprovedSpan(page_number=page_number, bboxes=bboxes, text=text)


def disposition_needs_change(
    existing_action: DispositionAction | None,
    desired_action: DispositionAction,
    *,
    is_edit: bool = False,
    current_text: str | None = None,
    new_text: str | None = None,
) -> bool:
    """Return whether a disposition write is required (vs. an idempotent no-op).

    A change is needed when the target span has no disposition yet, when the desired
    action differs from the existing one, or -- for an edit -- when the text differs.
    Bbox-only edit changes are checked separately by ``bboxes_differ`` (kept out of this
    function's signature to stay within the project's max-argument lint limit).
    """
    if existing_action != desired_action:
        return True
    return bool(is_edit and current_text != new_text)


def bboxes_differ(current_bboxes: list[Any], new_bboxes: list[BBox]) -> bool:
    """Return whether ``new_bboxes`` differs from the span's persisted ``current_bboxes``."""
    return [tuple(bbox) for bbox in current_bboxes] != list(new_bboxes)


# ---------------------------------------------------------------------------
# Projection (DB)
# ---------------------------------------------------------------------------


async def project_approved_spans(session: AsyncSession, job: RedactionJob) -> list[ApprovedSpan]:
    """Project every approved span on ``job``'s document into ``ApprovedSpan``s for apply.

    Only ``DispositionAction.APPROVED`` spans are burned in; rejected spans are excluded.
    Ordered by page then span id for deterministic output. Raises ``ValidationError`` if a
    span's stored ``bboxes`` cannot be coerced into the ``ApprovedSpan`` shape.
    """
    stmt = (
        select(Span, Page.page_number)
        .join(Page, col(Span.page_id) == col(Page.id))
        .join(Disposition, col(Disposition.span_id) == col(Span.id))
        .where(col(Page.document_id) == job.document_id)
        .where(col(Disposition.action) == DispositionAction.APPROVED)
        .order_by(col(Page.page_number), col(Span.id))
    )
    rows = (await session.execute(stmt)).all()
    return [build_approved_span(page_number=row[1], bboxes=row[0].bboxes, text=row[0].text) for row in rows]


# ---------------------------------------------------------------------------
# Disposition batch orchestration (DB)
# ---------------------------------------------------------------------------


async def apply_disposition_batch(
    session: AsyncSession,
    job: RedactionJob,
    items: list[DispositionItem],
    reviewer_id: UUID,
) -> DispositionBatchResult:
    """Apply a batch of disposition verbs to ``job``, returning per-outcome counts.

    Existing-span verbs (approve/reject/edit) update the unique-per-span disposition in
    place and append one audit entry each -- unless the item is an identical resubmission,
    which is skipped without writing an audit entry. ``add_manual_span`` always creates a
    new span (+ approved disposition + audit entry). All writes share the caller's session
    and transaction.
    """
    applied = 0
    skipped = 0
    spans_created = 0
    for item in items:
        if isinstance(item, AddManualSpanItem):
            await _add_manual_span(session, job, item, reviewer_id)
            spans_created += 1
            applied += 1
        elif await _apply_existing_span_disposition(session, job, item, reviewer_id):
            applied += 1
        else:
            skipped += 1
    return DispositionBatchResult(applied=applied, skipped=skipped, spans_created=spans_created)


async def _load_job_span(session: AsyncSession, job: RedactionJob, span_id: UUID) -> Span:
    """Load a span by id, enforcing that it belongs to ``job``'s document."""
    stmt = (
        select(Span)
        .join(Page, col(Span.page_id) == col(Page.id))
        .where(col(Span.id) == span_id)
        .where(col(Page.document_id) == job.document_id)
    )
    span = (await session.execute(stmt)).scalar_one_or_none()
    if span is None:
        msg = f"Span {span_id} not found for job {job.id}"
        raise SpanNotFoundError(msg)
    return span


async def _apply_existing_span_disposition(
    session: AsyncSession,
    job: RedactionJob,
    item: ApproveItem | RejectItem | EditItem,
    reviewer_id: UUID,
) -> bool:
    """Approve/reject/edit an existing span; return whether a state change was written."""
    span = await _load_job_span(session, job, item.span_id)
    desired_action = DISPOSITION_ACTION_BY_VERB[item.verb]
    is_edit = isinstance(item, EditItem)
    new_text = item.text if isinstance(item, EditItem) else None
    new_bboxes = item.bboxes if isinstance(item, EditItem) else None

    existing = (
        await session.execute(select(Disposition).where(col(Disposition.span_id) == span.id))
    ).scalar_one_or_none()

    needs_change = disposition_needs_change(
        existing.action if existing else None,
        desired_action,
        is_edit=is_edit,
        current_text=span.text,
        new_text=new_text,
    )
    if new_bboxes is not None and bboxes_differ(span.bboxes, new_bboxes):
        needs_change = True
    if not needs_change:
        return False

    if isinstance(item, EditItem):
        span.text = item.text
        if item.bboxes is not None:
            span.bboxes = [list(bbox) for bbox in item.bboxes]
        # Why: edit mutates the persisted span in place (rather than versioning it) because
        # this ticket's scope has no span-history/manifest feature (#9); the audit chain
        # (AuditEntry, appended below) preserves the pre-edit content via its digest, so
        # nothing is lost even though the row itself is overwritten.
        session.add(span)
        await session.flush()  # type: ignore[attr-defined]

    if existing is not None:
        existing.action = desired_action
        existing.reviewer_id = reviewer_id
        existing.reason = item.reason
        session.add(existing)
    else:
        session.add(Disposition(span_id=span.id, action=desired_action, reviewer_id=reviewer_id, reason=item.reason))
    await session.flush()  # type: ignore[attr-defined]

    await append_audit_entry(
        session,
        job.id,
        AuditEntryInput(
            action=AUDIT_ACTION_BY_VERB[item.verb],
            category=span.category,
            text=span.text,
            reviewer_id=reviewer_id,
            span_id=span.id,
        ),
    )
    return True


async def _get_or_create_page(session: AsyncSession, document_id: UUID, page_number: int) -> Page:
    """Return the page for ``(document_id, page_number)``, creating it if absent."""
    page = (
        await session.execute(
            select(Page).where(col(Page.document_id) == document_id).where(col(Page.page_number) == page_number)
        )
    ).scalar_one_or_none()
    if page is None:
        page = Page(document_id=document_id, page_number=page_number)
        session.add(page)
        await session.flush()  # type: ignore[attr-defined]
    return page


async def _add_manual_span(
    session: AsyncSession,
    job: RedactionJob,
    item: AddManualSpanItem,
    reviewer_id: UUID,
) -> None:
    """Create a reviewer-authored manual span with an approved disposition + audit entry."""
    page = await _get_or_create_page(session, job.document_id, item.page_number)
    span = Span(
        page_id=page.id,
        bboxes=[list(bbox) for bbox in item.bboxes],
        text=item.text,
        category=item.category,
        source_tier=SourceTier.MANUAL,
        confidence=None,
    )
    session.add(span)
    await session.flush()  # type: ignore[attr-defined]

    session.add(
        Disposition(span_id=span.id, action=DispositionAction.APPROVED, reviewer_id=reviewer_id, reason=item.reason)
    )
    await session.flush()  # type: ignore[attr-defined]

    await append_audit_entry(
        session,
        job.id,
        AuditEntryInput(
            action=AuditAction.MANUAL_SPAN_ADDED,
            category=item.category,
            text=item.text,
            reviewer_id=reviewer_id,
            span_id=span.id,
        ),
    )
