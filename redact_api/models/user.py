"""User table and related API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

import sqlalchemy as sa
from pydantic import ConfigDict, EmailStr, ValidationInfo, field_validator
from sqlmodel import Field, SQLModel

from redact_api.models.base import TimestampedTable
from redact_api.models.shared import OrganizationInfo

# Constants for validation
MAX_NAME_LENGTH = 100


class UserBase(SQLModel):
    email: EmailStr = Field(description="User email address")
    name: str = Field(min_length=1, description="User full name")
    kratos_identity_id: UUID | None = Field(
        default=None,
        unique=True,
        index=True,
        description="Ory Kratos identity UUID (one-to-one mapping)",
    )


class User(TimestampedTable, UserBase, table=True):
    __tablename__ = "app_user"

    __table_args__ = (
        sa.UniqueConstraint(
            "email",
            name="uq_app_user_email",
        ),
    )


class UserCreate(UserBase):
    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str, info: ValidationInfo) -> str:  # noqa: ARG003
        """Validate user name field.

        Args:
            value: The name value to validate
            info: Pydantic validation context

        Returns:
            The validated and trimmed name

        Raises:
            ValueError: If name is empty/whitespace or exceeds max length
        """
        value = value.strip()
        if not value:
            msg = "Name cannot be empty or whitespace"
            raise ValueError(msg)
        if len(value) > MAX_NAME_LENGTH:
            msg = f"Name must be {MAX_NAME_LENGTH} characters or less"
            raise ValueError(msg)
        return value


class UserRead(UserBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    organizations: list[OrganizationInfo] = Field(default_factory=list)

    # SQLModel expects SQLModelConfig but accepts ConfigDict at runtime
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)  # type: ignore[assignment]


class UserUpdate(SQLModel):
    email: EmailStr | None = None
    name: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None, info: ValidationInfo) -> str | None:  # noqa: ARG003
        """Validate user name field.

        Args:
            value: The name value to validate
            info: Pydantic validation context

        Returns:
            The validated and trimmed name, or None if not provided

        Raises:
            ValueError: If name is empty/whitespace or exceeds max length
        """
        if value is not None:
            value = value.strip()
            if not value:
                msg = "Name cannot be empty or whitespace"
                raise ValueError(msg)
            if len(value) > MAX_NAME_LENGTH:
                msg = f"Name must be {MAX_NAME_LENGTH} characters or less"
                raise ValueError(msg)
        return value
