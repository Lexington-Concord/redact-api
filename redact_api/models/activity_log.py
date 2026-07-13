"""Activity log table and related API schemas."""

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


class ActivityAction(StrEnum):
    """Activity action values.

    IMPORTANT: Inherit from StrEnum for proper JSON serialization.
    """

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"


class ActivityLogBase(SQLModel):
    """Base activity log model with common fields."""

    action: ActivityAction = Field(sa_column=sa.Column(sa.String(), nullable=False))
    resource_type: str = Field(description="Type of resource (e.g., 'user', 'organization', 'document')")
    resource_id: UUID | None = Field(default=None, description="ID of the resource being acted upon")
    details: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=sa.Column(JSONB, nullable=False, server_default="{}"),
    )


class ActivityLog(TimestampedTable, ActivityLogBase, table=True):
    """Activity log table for tracking actions."""

    __tablename__ = "activity_log"


class ActivityLogArchive(TimestampedTable, table=True):
    """Archive table for activity logs older than retention period."""

    __tablename__ = "activity_log_archive"

    action: ActivityAction = Field(sa_column=sa.Column(sa.String(), nullable=False))
    resource_type: str
    resource_id: UUID | None = None
    details: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=sa.Column(JSONB, nullable=False, server_default="{}"),
    )
    archived_at: datetime = Field(
        sa_column=sa.Column(
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
    )


class ActivityLogRead(ActivityLogBase):
    """Schema for reading an activity log entry."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    # SQLModel expects SQLModelConfig but accepts ConfigDict at runtime
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)  # type: ignore[assignment]
