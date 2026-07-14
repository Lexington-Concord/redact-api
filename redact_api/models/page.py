"""Page table: a single page of a Document within the redaction pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

import sqlalchemy as sa
from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

from redact_api.models.base import TimestampedTable


class PageBase(SQLModel):
    """Shared page fields."""

    document_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("document.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    page_number: int = Field(description="1-based page index within the document")


class Page(TimestampedTable, PageBase, table=True):
    """A page of a document; parent of detected spans."""

    __tablename__ = "page"

    __table_args__ = (
        sa.UniqueConstraint("document_id", "page_number", name="uq_page_document_page_number"),
        sa.Index("ix_page_document_id", "document_id"),
    )


class PageCreate(PageBase):
    """Schema for creating a page."""


class PageRead(PageBase):
    """Schema for reading a page."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    # SQLModel expects SQLModelConfig but accepts ConfigDict at runtime
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)  # type: ignore[assignment]
