"""Organization table and related API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import ConfigDict, ValidationInfo, field_validator
from sqlmodel import Field, SQLModel

from redact_api.models.base import TimestampedTable
from redact_api.models.shared import UserInfo

# Constants for validation
MAX_ORG_NAME_LENGTH = 255


class OrganizationBase(SQLModel):
    name: str


class Organization(TimestampedTable, OrganizationBase, table=True):
    pass


class OrganizationCreate(OrganizationBase):
    """Schema for creating a new organization.

    Note: Uniqueness of organization name must be enforced at the service/database
    layer, as validators cannot perform database queries.
    """

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str, info: ValidationInfo) -> str:  # noqa: ARG003
        """Validate organization name field.

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
            msg = "Organization name cannot be empty or whitespace"
            raise ValueError(msg)
        if len(value) > MAX_ORG_NAME_LENGTH:
            msg = f"Organization name must be {MAX_ORG_NAME_LENGTH} characters or less"
            raise ValueError(msg)
        return value


class OrganizationRead(OrganizationBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    users: list[UserInfo] = Field(default_factory=list)

    # SQLModel expects SQLModelConfig but accepts ConfigDict at runtime
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)  # type: ignore[assignment]


class OrganizationUpdate(SQLModel):
    name: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None, info: ValidationInfo) -> str | None:  # noqa: ARG003
        """Validate organization name field.

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
                msg = "Organization name cannot be empty or whitespace"
                raise ValueError(msg)
            if len(value) > MAX_ORG_NAME_LENGTH:
                msg = f"Organization name must be {MAX_ORG_NAME_LENGTH} characters or less"
                raise ValueError(msg)
        return value
