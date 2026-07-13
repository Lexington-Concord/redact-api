"""Membership table and API schemas for user-organization links."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import ClassVar
from uuid import UUID

import sqlalchemy as sa
from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

from redact_api.models.base import TimestampedTable


class MembershipRole(enum.StrEnum):
    """Role levels for organization members.

    Roles enforce a hierarchy: OWNER > ADMIN > MEMBER

    - OWNER: Full control including org deletion and role management
    - ADMIN: Can manage members and update organization settings
    - MEMBER: Can use organization resources
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class MembershipBase(SQLModel):
    user_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    organization_id: UUID = Field(
        sa_column=sa.Column(
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    role: MembershipRole = Field(
        default=MembershipRole.MEMBER,
        sa_column=sa.Column(
            sa.Enum(MembershipRole, name="membership_role", native_enum=False),
            nullable=False,
            server_default="member",
        ),
    )


class Membership(TimestampedTable, MembershipBase, table=True):
    __tablename__ = "membership"

    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "organization_id",
            name="uq_membership_user_org",
        ),
        sa.Index("ix_membership_user_id", "user_id"),
        sa.Index("ix_membership_organization_id", "organization_id"),
    )


class MembershipCreate(MembershipBase):
    """Schema for creating a new membership.

    Note: The combination of user_id and organization_id must be unique, which is
    enforced by the database constraint 'uq_membership_user_org' in the Membership
    table definition.
    """


class MembershipUpdate(SQLModel):
    """Schema for updating membership (primarily role changes)."""

    role: MembershipRole | None = None


class MembershipRead(MembershipBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    # SQLModel expects SQLModelConfig but accepts ConfigDict at runtime
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)  # type: ignore[assignment]
