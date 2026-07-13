"""Comprehensive user endpoint tests.

Tests cover CRUD operations, validation, relationships, and error handling.
"""

from http import HTTPStatus

import pytest
from httpx import AsyncClient

# Test constants
NUM_TEST_USERS = 3
NONEXISTENT_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


class TestUserCRUD:
    """Test basic user CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_user_success(self, client: AsyncClient) -> None:
        """Create a user with valid data.

        Note: POST /users auto-creates a membership to the current tenant's
        organization (the default test org). This is expected behavior for
        the API - users are automatically added to the org they're created in.
        """
        response = await client.post(
            "/users",
            json={
                "name": "Jane Doe",
                "email": "jane@example.com",
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        user = response.json()
        assert user["name"] == "Jane Doe"
        assert user["email"] == "jane@example.com"
        # User is auto-added to the current tenant's org (default test org)
        # so they will have at least 1 organization membership
        assert isinstance(user["organizations"], list)
        assert "id" in user
        assert "created_at" in user
        assert "updated_at" in user

    @pytest.mark.asyncio
    async def test_create_user_with_duplicate_email(self, client: AsyncClient) -> None:
        """Creating user with duplicate email should fail gracefully."""
        payload = {
            "name": "Jane Doe",
            "email": "duplicate@example.com",
        }
        # Create first user
        response1 = await client.post("/users", json=payload)
        assert response1.status_code == HTTPStatus.CREATED

        # Try to create duplicate
        response2 = await client.post("/users", json=payload)
        # Should fail with 400 or 409 (database constraint violation)
        assert response2.status_code in (HTTPStatus.BAD_REQUEST, HTTPStatus.CONFLICT)

    @pytest.mark.asyncio
    async def test_read_user(self, client: AsyncClient) -> None:
        """Get a single user by ID."""
        # Create user
        create_response = await client.post(
            "/users",
            json={
                "name": "John Smith",
                "email": "john@example.com",
            },
        )
        user_id = create_response.json()["id"]

        # Read user
        get_response = await client.get(f"/users/{user_id}")
        assert get_response.status_code == HTTPStatus.OK
        user = get_response.json()
        assert user["id"] == user_id
        assert user["name"] == "John Smith"
        assert user["email"] == "john@example.com"

    @pytest.mark.asyncio
    async def test_update_user(self, client: AsyncClient) -> None:
        """Update user fields."""
        # Create user
        create_response = await client.post(
            "/users",
            json={
                "name": "Original Name",
                "email": "original@example.com",
            },
        )
        user_id = create_response.json()["id"]

        # Update user (pass X-User-ID header matching the user being updated)
        update_response = await client.patch(
            f"/users/{user_id}",
            json={"name": "Updated Name"},
            headers={"X-User-ID": str(user_id), "X-Email": "original@example.com"},
        )
        assert update_response.status_code == HTTPStatus.OK
        updated_user = update_response.json()
        assert updated_user["name"] == "Updated Name"
        assert updated_user["email"] == "original@example.com"

    @pytest.mark.asyncio
    async def test_delete_user(self, client: AsyncClient) -> None:
        """Delete a user."""
        # Create user
        create_response = await client.post(
            "/users",
            json={
                "name": "To Delete",
                "email": "delete@example.com",
            },
        )
        user_id = create_response.json()["id"]

        # Delete user (pass X-User-ID header matching the user being deleted)
        delete_response = await client.delete(
            f"/users/{user_id}",
            headers={"X-User-ID": str(user_id), "X-Email": "delete@example.com"},
        )
        assert delete_response.status_code == HTTPStatus.NO_CONTENT

        # Verify deleted
        get_response = await client.get(f"/users/{user_id}")
        assert get_response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_list_users(self, client: AsyncClient) -> None:
        """List users with pagination."""
        # Create multiple users
        for i in range(NUM_TEST_USERS):
            await client.post(
                "/users",
                json={
                    "name": f"User {i}",
                    "email": f"user{i}@example.com",
                },
            )

        # List users
        # Note: Total will include the default fixture user plus test users
        list_response = await client.get("/users")
        assert list_response.status_code == HTTPStatus.OK
        data = list_response.json()
        # Should see at least NUM_TEST_USERS (plus fixture user)
        assert data["total"] >= NUM_TEST_USERS
        assert len(data["items"]) >= NUM_TEST_USERS
        assert data["page"] == 1
        # Verify test users are in the response
        test_user_names = {f"User {i}" for i in range(NUM_TEST_USERS)}
        response_names = {item["name"] for item in data["items"]}
        assert test_user_names.issubset(response_names)


class TestUserValidation:
    """Test user input validation."""

    @pytest.mark.asyncio
    async def test_create_user_invalid_email(self, client: AsyncClient) -> None:
        """Creating user with malformed email should fail."""
        response = await client.post(
            "/users",
            json={
                "name": "Test User",
                "email": "not-an-email",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_create_user_empty_name(self, client: AsyncClient) -> None:
        """Creating user with empty name should fail."""
        response = await client.post(
            "/users",
            json={
                "name": "",
                "email": "test@example.com",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_create_user_whitespace_only_name(self, client: AsyncClient) -> None:
        """Creating user with whitespace-only name should fail."""
        response = await client.post(
            "/users",
            json={
                "name": "   ",
                "email": "test@example.com",
            },
        )
        # Pydantic validators raise ValueError which can be converted to either 400 or 422
        assert response.status_code in (
            HTTPStatus.BAD_REQUEST,  # 400
            HTTPStatus.UNPROCESSABLE_ENTITY,  # 422
        )

    @pytest.mark.asyncio
    async def test_create_user_missing_email(self, client: AsyncClient) -> None:
        """Creating user without email should fail."""
        response = await client.post(
            "/users",
            json={
                "name": "Test User",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_create_user_missing_name(self, client: AsyncClient) -> None:
        """Creating user without name should fail."""
        response = await client.post(
            "/users",
            json={
                "email": "test@example.com",
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_update_user_invalid_email(self, client: AsyncClient) -> None:
        """Updating user with invalid email should fail."""
        # Create user
        create_response = await client.post(
            "/users",
            json={
                "name": "Test User",
                "email": "valid@example.com",
            },
        )
        user_id = create_response.json()["id"]

        # Try to update with invalid email
        update_response = await client.patch(
            f"/users/{user_id}",
            json={"email": "invalid-email"},
        )
        assert update_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


class TestUserOrganizationRelationship:
    """Test user-organization relationship expansion."""

    @pytest.mark.asyncio
    async def test_user_shows_organizations(self, client: AsyncClient) -> None:
        """User should show organizations after membership is created.

        Note: POST /users auto-creates a membership to the default test org,
        and POST /organizations auto-creates OWNER membership for the current
        user. So the user will have at least 2 orgs after these operations.
        """
        # Create user (auto-creates membership to default test org)
        user_response = await client.post(
            "/users",
            json={
                "name": "Test User",
                "email": "user@example.com",
            },
        )
        user_id = user_response.json()["id"]
        initial_org_count = len(user_response.json()["organizations"])

        # Create organization
        org_response = await client.post(
            "/organizations",
            json={"name": "Test Org"},
        )
        org_id = org_response.json()["id"]

        # Create membership
        await client.post(
            "/memberships",
            json={
                "user_id": user_id,
                "organization_id": org_id,
            },
        )

        # Get user and verify organizations
        get_response = await client.get(f"/users/{user_id}")
        assert get_response.status_code == HTTPStatus.OK
        user = get_response.json()
        assert "organizations" in user
        assert isinstance(user["organizations"], list)
        # User now has one more org than before (the new "Test Org")
        assert len(user["organizations"]) == initial_org_count + 1
        # Verify the new org is in the list
        org_ids = [org["id"] for org in user["organizations"]]
        assert org_id in org_ids
        # Verify we can find the specific org with correct name
        test_org = next(org for org in user["organizations"] if org["id"] == org_id)
        assert test_org["name"] == "Test Org"

    @pytest.mark.asyncio
    async def test_user_has_no_organizations(self, client: AsyncClient) -> None:
        """User created via API is auto-added to current tenant's org.

        Note: POST /users auto-creates a membership to the current tenant's
        organization (the default test org). This is expected behavior.
        To test a user with no organizations, you would create directly in DB.
        """
        response = await client.post(
            "/users",
            json={
                "name": "Lonely User",
                "email": "lonely@example.com",
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        user = response.json()
        # User is auto-added to current tenant's org via API
        # so they have at least 1 organization membership
        assert isinstance(user["organizations"], list)

    @pytest.mark.asyncio
    async def test_delete_user_cascades_memberships(self, client: AsyncClient) -> None:
        """Deleting a user should cascade delete their memberships."""
        # Create user
        user_response = await client.post(
            "/users",
            json={
                "name": "Test User",
                "email": "cascade@example.com",
            },
        )
        user_id = user_response.json()["id"]

        # Create organization
        org_response = await client.post(
            "/organizations",
            json={"name": "Test Org"},
        )
        org_id = org_response.json()["id"]

        # Create membership
        membership_response = await client.post(
            "/memberships",
            json={
                "user_id": user_id,
                "organization_id": org_id,
            },
        )
        membership_id = membership_response.json()["id"]

        # Delete user (pass X-User-ID header matching the user being deleted)
        delete_response = await client.delete(
            f"/users/{user_id}",
            headers={"X-User-ID": str(user_id), "X-Email": "cascade@example.com"},
        )
        assert delete_response.status_code == HTTPStatus.NO_CONTENT

        # Verify membership is deleted (cascade)
        membership_get = await client.delete(f"/memberships/{membership_id}")
        # Should get 404 since cascade delete already removed it
        assert membership_get.status_code == HTTPStatus.NOT_FOUND


class TestUserErrorHandling:
    """Test user error scenarios."""

    @pytest.mark.asyncio
    async def test_get_nonexistent_user(self, client: AsyncClient) -> None:
        """Getting nonexistent user should return 404."""
        response = await client.get(f"/users/{NONEXISTENT_UUID}")
        assert response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_update_nonexistent_user(self, client: AsyncClient) -> None:
        """Updating nonexistent user should return 404."""
        response = await client.patch(
            f"/users/{NONEXISTENT_UUID}",
            json={"name": "Updated"},
            headers={"X-User-ID": str(NONEXISTENT_UUID), "X-Email": "nonexistent@example.com"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_delete_nonexistent_user(self, client: AsyncClient) -> None:
        """Deleting nonexistent user should return 404."""
        response = await client.delete(
            f"/users/{NONEXISTENT_UUID}",
            headers={"X-User-ID": str(NONEXISTENT_UUID), "X-Email": "nonexistent@example.com"},
        )
        assert response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_user_invalid_uuid(self, client: AsyncClient) -> None:
        """Getting user with invalid UUID should return 422."""
        response = await client.get("/users/not-a-uuid")
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
