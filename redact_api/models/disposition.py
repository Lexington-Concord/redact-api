"""Disposition table: a reviewer's approve/reject decision on a span."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

import sqlalchemy as sa
from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

from redact_api.models.base import TimestampedTable


class DispositionAction(StrEnum):
    """Reviewer decision on a span. Edits are recorded as AuditEntry rows, not here."""

    APPROVED = "approved"
    REJECTED = "rejected"


class DispositionBase(SQLModel):
    """Shared disposition fields."""

    span_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("span.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        )
    )
    action: DispositionAction = Field(
        sa_column=sa.Column(
            sa.Enum(DispositionAction, name="disposition_action", native_enum=False),
            nullable=False,
        )
    )
    reason: str | None = Field(default=None, description="Optional reviewer note")
    reviewer_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )


class Disposition(TimestampedTable, DispositionBase, table=True):
    """A one-to-one decision on a span."""

    __tablename__ = "disposition"


class DispositionCreate(DispositionBase):
    """Schema for creating a disposition."""


class DispositionRead(DispositionBase):
    """Schema for reading a disposition."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    # SQLModel expects SQLModelConfig but accepts ConfigDict at runtime
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)  # type: ignore[assignment]
