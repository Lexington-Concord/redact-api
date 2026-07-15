"""RedactionJob table: the aggregate root tracking a document's redaction lifecycle."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

import sqlalchemy as sa
from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

from redact_api.models.base import TimestampedTable


class JobStatus(StrEnum):
    """Lifecycle state of a redaction job.

    The happy path is a linear chain UPLOADED -> INGESTED -> DETECTED -> IN_REVIEW ->
    APPLYING -> VERIFIED -> EXPORTED. FAILED is a terminal error state reachable from
    any non-terminal state. The allowed transitions are enforced in
    ``redact_api.services.redaction_job_service.VALID_TRANSITIONS``.
    """

    UPLOADED = "uploaded"
    INGESTED = "ingested"
    DETECTED = "detected"
    IN_REVIEW = "in_review"
    APPLYING = "applying"
    VERIFIED = "verified"
    EXPORTED = "exported"
    FAILED = "failed"


class RedactionJobBase(SQLModel):
    """Shared redaction-job fields."""

    document_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("document.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        )
    )
    organization_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    status: JobStatus = Field(
        default=JobStatus.UPLOADED,
        sa_column=sa.Column(
            sa.Enum(JobStatus, name="job_status", native_enum=False),
            nullable=False,
            server_default=JobStatus.UPLOADED.value,
        ),
    )


class RedactionJob(TimestampedTable, RedactionJobBase, table=True):
    """One redaction job per document (aggregate root)."""

    __tablename__ = "redaction_job"

    # Storage key of the verified redacted PDF, set once ``apply`` passes the verify gate;
    # ``None`` until then. Read back verbatim by export -- export never recomputes.
    redacted_pdf_key: str | None = Field(default=None, nullable=True)

    __table_args__ = (sa.Index("ix_redaction_job_organization_id", "organization_id"),)


class RedactionJobCreate(SQLModel):
    """Schema for creating a redaction job.

    Deliberately does not inherit ``RedactionJobBase``: ``status`` is server-controlled
    (always starts at ``UPLOADED`` and only moves via ``transition_job_status``), so it
    must not be a client-settable field on this schema.
    """

    document_id: UUID
    organization_id: UUID


class RedactionJobRead(RedactionJobBase):
    """Schema for reading a redaction job."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    # SQLModel expects SQLModelConfig but accepts ConfigDict at runtime
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)  # type: ignore[assignment]
