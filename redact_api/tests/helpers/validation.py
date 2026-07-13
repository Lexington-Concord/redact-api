"""Test validation helpers for API response assertions.

Provides reusable assertion functions for validating API responses, schemas,
and data consistency across tests.

Usage:
    from redact_api.tests.helpers import assert_user_response

    def test_create_user(client):
        response = await client.post("/users", json={...})
        assert response.status_code == 201
        assert_user_response(response.json())
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID


def validate_uuid_field(
    value: Any,  # noqa: ANN401
    field_name: str = "id",
) -> UUID:
    """Validate that a value is a valid UUID string.

    Args:
        value: The value to validate as UUID
        field_name: Name of field for error messages

    Returns:
        UUID object if valid

    Raises:
        TypeError: If value is not a valid UUID string
    """
    if not isinstance(value, str):
        msg = f"{field_name} must be a string, got {type(value)}"
        raise TypeError(msg)
    try:
        return UUID(value)
    except ValueError as e:
        msg = f"{field_name} is not a valid UUID: {value}"
        raise AssertionError(msg) from e


def validate_datetime_iso_format(
    value: Any,  # noqa: ANN401
    field_name: str = "timestamp",
) -> datetime:
    """Validate that a value is a valid ISO 8601 datetime string.

    Args:
        value: The value to validate
        field_name: Name of field for error messages

    Returns:
        Parsed datetime object if valid

    Raises:
        TypeError: If value is not a valid ISO format datetime
    """
    if not isinstance(value, str):
        msg = f"{field_name} must be a string, got {type(value)}"
        raise TypeError(msg)
    try:
        # Try parsing with timezone first (most common)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        msg = f"{field_name} is not valid ISO 8601 format: {value}"
        raise AssertionError(msg) from e


def validate_pagination_response(response_data: dict[str, Any], min_items: int = 0, max_items: int = 1000) -> None:
    """Validate pagination response structure.

    FastAPI pagination responses should have:
    - items: list of items
    - total: total count
    - page: current page (optional)
    - size: items per page (optional)

    Args:
        response_data: Response JSON to validate
        min_items: Minimum expected number of items
        max_items: Maximum expected number of items

    Raises:
        AssertionError: If pagination structure is invalid
    """
    assert isinstance(response_data, dict), "Response must be a dict"
    assert "items" in response_data, "Response must have 'items' field"
    assert "total" in response_data, "Response must have 'total' field"
    assert isinstance(response_data["items"], list), "'items' must be a list"
    assert isinstance(response_data["total"], int), "'total' must be an integer"
    item_count = len(response_data["items"])
    assert min_items <= item_count <= max_items, f"Item count {item_count} not in range [{min_items}, {max_items}]"
    assert response_data["total"] >= len(response_data["items"]), "total must be >= items count"


def assert_user_response(response_data: dict[str, Any]) -> None:
    """Assert that response matches UserRead schema.

    Validates:
    - Required fields: id, email, name, created_at, updated_at, organizations
    - Field types and formats
    - Organizations is a list

    Args:
        response_data: Response JSON from user endpoint

    Raises:
        AssertionError: If response doesn't match UserRead schema
    """
    # Validate required fields exist
    required_fields = {"id", "email", "name", "created_at", "updated_at", "organizations"}
    assert required_fields.issubset(response_data.keys()), (
        f"Missing required fields: {required_fields - response_data.keys()}"
    )

    # Validate field types and formats
    validate_uuid_field(response_data["id"], "id")
    assert isinstance(response_data["email"], str), "email must be string"
    assert isinstance(response_data["name"], str), "name must be string"
    validate_datetime_iso_format(response_data["created_at"], "created_at")
    validate_datetime_iso_format(response_data["updated_at"], "updated_at")

    # Validate organizations
    assert isinstance(response_data["organizations"], list), "organizations must be a list"

    # Validate email format (basic check)
    assert "@" in response_data["email"], "email must be valid format"
    assert len(response_data["name"]) > 0, "name must not be empty"


def assert_organization_response(response_data: dict[str, Any]) -> None:
    """Assert that response matches OrganizationRead schema.

    Validates:
    - Required fields: id, name, created_at, updated_at, users
    - Field types and formats
    - Users is a list

    Args:
        response_data: Response JSON from organization endpoint

    Raises:
        AssertionError: If response doesn't match OrganizationRead schema
    """
    # Validate required fields exist
    required_fields = {"id", "name", "created_at", "updated_at", "users"}
    assert required_fields.issubset(response_data.keys()), (
        f"Missing required fields: {required_fields - response_data.keys()}"
    )

    # Validate field types and formats
    validate_uuid_field(response_data["id"], "id")
    assert isinstance(response_data["name"], str), "name must be string"
    validate_datetime_iso_format(response_data["created_at"], "created_at")
    validate_datetime_iso_format(response_data["updated_at"], "updated_at")

    # Validate users
    assert isinstance(response_data["users"], list), "users must be a list"
    assert len(response_data["name"]) > 0, "name must not be empty"


def assert_error_response(response_data: dict[str, Any], expected_detail: str | None = None) -> None:
    """Assert that response is a valid error response.

    Validates error response structure with optional detail matching.

    Args:
        response_data: Response JSON from error endpoint
        expected_detail: Optional expected detail message to match

    Raises:
        AssertionError: If response doesn't match error schema
    """
    assert isinstance(response_data, dict), "Error response must be a dict"
    assert "detail" in response_data, "Error response must have 'detail' field"
    assert isinstance(response_data["detail"], (str, list)), "'detail' must be string or list"

    if expected_detail is not None:
        if isinstance(response_data["detail"], str):
            assert expected_detail in response_data["detail"], (
                f"Expected detail '{expected_detail}' in '{response_data['detail']}'"
            )
        else:
            # Handle validation error details (list of errors)
            detail_strs = [d if isinstance(d, str) else d.get("msg", "") for d in response_data["detail"]]
            assert any(expected_detail in d for d in detail_strs), f"Expected '{expected_detail}' in error details"
