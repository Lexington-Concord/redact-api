"""Span table: a candidate PII region detected on a page."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar
from uuid import UUID

import sqlalchemy as sa
from pydantic import ConfigDict
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from redact_api.models.base import TimestampedTable


class SourceTier(StrEnum):
    """Detection provenance tier for a candidate span.

    Reflects how the span was detected (not how the verify gate later re-checks
    recoverability -- that's ``redact_api.redaction.models.CheckType``, a separate
    taxonomy). ``TIER_1``/``TIER_2``/``TIER_3`` rank detector confidence for a
    candidate; ``MANUAL`` marks reviewer-added spans (see
    ``AuditAction.MANUAL_SPAN_ADDED``).
    """

    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"
    MANUAL = "manual"


class SpanBase(SQLModel):
    """Shared span fields."""

    page_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("page.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    bboxes: list[Any] = Field(
        default_factory=list,
        sa_column=sa.Column(JSONB, nullable=False, server_default="[]"),
    )
    text: str = Field(description="Raw candidate text (working data, redacted before export)")
    category: str = Field(description="Free-text PII category label")
    source_tier: SourceTier = Field(
        sa_column=sa.Column(
            sa.Enum(SourceTier, name="source_tier", native_enum=False),
            nullable=False,
        )
    )
    confidence: float | None = Field(default=None, description="Optional detector confidence score")


class Span(TimestampedTable, SpanBase, table=True):
    """A detected candidate PII span; parent of at most one disposition."""

    __tablename__ = "span"

    __table_args__ = (sa.Index("ix_span_page_id", "page_id"),)


class SpanCreate(SpanBase):
    """Schema for creating a span."""


class SpanRead(SpanBase):
    """Schema for reading a span."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    # SQLModel expects SQLModelConfig but accepts ConfigDict at runtime
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)  # type: ignore[assignment]
