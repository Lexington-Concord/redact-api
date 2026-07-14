"""AuditEntry table: append-only, hash-chained audit trail for a redaction job.

Entries never store raw span text -- only a category label and a SHA-256 digest of the
normalized text -- so the audit trail carries no recoverable PII. Rows are immutable:
each entry's ``entry_hash`` chains off the previous entry's, and all foreign keys use
RESTRICT so audited jobs and their referents cannot be deleted out from under the trail.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

import sqlalchemy as sa
from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

from redact_api.models.base import TimestampedTable


class AuditAction(StrEnum):
    """The reviewer action an audit entry records. Distinct from DispositionAction."""

    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    MANUAL_SPAN_ADDED = "manual_span_added"


class AuditEntryBase(SQLModel):
    """Shared audit-entry fields."""

    job_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("redaction_job.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    span_id: UUID | None = Field(
        default=None,
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("span.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    reviewer_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    organization_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    action: AuditAction = Field(
        sa_column=sa.Column(
            sa.Enum(AuditAction, name="audit_action", native_enum=False),
            nullable=False,
        )
    )
    category: str = Field(description="PII category label (carries no raw text)")
    text_hash: str = Field(description="SHA-256 hex digest of the normalized span text")
    entry_hash: str = Field(description="SHA-256 hex digest chaining this entry to prev_hash")
    prev_hash: str = Field(description="entry_hash of the previous entry, or genesis for the first")
    sequence: int = Field(description="Monotonic per-job ordinal for deterministic chaining")


class AuditEntry(TimestampedTable, AuditEntryBase, table=True):
    """An immutable, hash-chained audit-trail row."""

    __tablename__ = "audit_entry"

    __table_args__ = (
        sa.UniqueConstraint("job_id", "sequence", name="uq_audit_entry_job_sequence"),
        sa.Index("ix_audit_entry_organization_id", "organization_id"),
        sa.Index("ix_audit_entry_span_id", "span_id"),
    )


class AuditEntryRead(AuditEntryBase):
    """Schema for reading an audit entry."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    # SQLModel expects SQLModelConfig but accepts ConfigDict at runtime
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)  # type: ignore[assignment]
