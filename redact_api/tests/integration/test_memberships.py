"""Membership endpoint tests for CRUD, constraints, cascade delete, and errors."""

from http import HTTPStatus

import pytest
from httpx import AsyncClient

# Test constants
EXPECTED_USER_COUNT = 3


class TestMembershipCRUD:
    """Test basic membership CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_membership_success(self, client: AsyncClient) -> None:
        """Create a membership with valid user and organization."""
        # Create organization
        org_response = await client.post("/organizations", json={"name": "Acme"})
        assert org_response.status_code == HTTPStatus.CREATED
        organization_id = org_response.json()["id"]

        # Create user
        user_response = await client.post(
            "/users",
            json={"name": "Jane Doe", "email": "jane@example.com"},
        )
        assert user_response.status_code == HTTPStatus.CREATED
        user_id = user_response.json()["id"]

        # Create membership
        create_response = await client.post(
            "/memberships",
            json={"user_id": user_id, "organization_id": organization_id},
        )
        assert create_response.status_code == HTTPStatus.CREATED
        membership = create_response.json()
        assert membership["user_id"] == user_id
        assert membership["organization_id"] == organization_id
        assert "id" in membership
        assert "created_at" in membership
        assert "updated_at" in membership

    @pytest.mark.asyncio
    async def test_delete_membership(self, client: AsyncClient) -> None:
        """Delete a membership.

        Note: Creating a user auto-creates a membership to the current tenant's org.
        Creating an org auto-creates OWNER membership for the current user.
        This test verifies that we can delete an *additional* membership.
        """
        # Create organization - auto-creates OWNER membership for current test user
        org_response = await client.post("/organizations", json={"name": "Acme"})
        organization_id = org_response.json()["id"]

        # Create user - auto-creates membership to default test org
        user_response = await client.post(
            "/users",
            json={"name": "Jane Doe", "email": "jane@example.com"},
        )
        user_id = user_response.json()["id"]
        initial_org_count = len(user_response.json()["organizations"])

        # Create additional membership for Jane to Acme
        create_response = await client.post(
            "/memberships",
            json={"user_id": user_id, "organization_id": organization_id},
        )
        membership_id = create_response.json()["id"]

        # Verify user now has one more organization
        user_before = await client.get(f"/users/{user_id}")
        assert len(user_before.json()["organizations"]) == initial_org_count + 1

        # Get Acme's initial user count (should have test user + Jane)
        org_before = await client.get(f"/organizations/{organization_id}")
        initial_user_count = len(org_before.json()["users"])

        # Delete Jane's membership to Acme
        delete_response = await client.delete(f"/memberships/{membership_id}")
        assert delete_response.status_code == HTTPStatus.NO_CONTENT

        # Verify user is back to only the auto-created membership
        user_get = await client.get(f"/users/{user_id}")
        assert user_get.status_code == HTTPStatus.OK
        assert len(user_get.json()["organizations"]) == initial_org_count

        # Verify Acme has one fewer user (Jane removed, test user remains as OWNER)
        org_get = await client.get(f"/organizations/{organization_id}")
        assert org_get.status_code == HTTPStatus.OK
        assert len(org_get.json()["users"]) == initial_user_count - 1

    @pytest.mark.asyncio
    async def test_list_memberships(self, client: AsyncClient) -> None:
        """List all memberships with pagination.

        Note: POST /organizations auto-creates OWNER membership for the current
        user (default test user). So when we create test users and add them to
        the org, the org will have EXPECTED_USER_COUNT + 1 memberships.
        """
        # Create organization (auto-creates OWNER membership for default test user)
        org_response = await client.post("/organizations", json={"name": "Acme"})
        organization_id = org_response.json()["id"]

        # Create multiple users and memberships
        created_user_ids = []
        for i in range(EXPECTED_USER_COUNT):
            user_response = await client.post(
                "/users",
                json={"name": f"User {i}", "email": f"user{i}@example.com"},
            )
            user_id = user_response.json()["id"]
            created_user_ids.append(user_id)

            await client.post(
                "/memberships",
                json={"user_id": user_id, "organization_id": organization_id},
            )

        # List memberships
        # Note: Total will include the default fixture membership plus test memberships
        list_response = await client.get("/memberships")
        assert list_response.status_code == HTTPStatus.OK
        data = list_response.json()
        # Should see at least EXPECTED_USER_COUNT memberships (plus fixture memberships)
        assert data["total"] >= EXPECTED_USER_COUNT
        assert len(data["items"]) >= EXPECTED_USER_COUNT

        # Verify that the created users' memberships are in the response
        # Note: Org also has the default test user's OWNER membership
        org_memberships = [item for item in data["items"] if item["organization_id"] == organization_id]
        # Should have EXPECTED_USER_COUNT + 1 (default test user as OWNER)
        assert len(org_memberships) >= EXPECTED_USER_COUNT
        # Verify all our created users have memberships
        org_user_ids = {item["user_id"] for item in org_memberships}
        for user_id in created_user_ids:
            assert user_id in org_user_ids


class TestMembershipConstraints:
    """Test membership database constraints."""

    @pytest.mark.asyncio
    async def test_duplicate_membership_fails(self, client: AsyncClient) -> None:
        """Creating duplicate membership (same user+org) should fail."""
        # Create organization and user
        org_response = await client.post("/organizations", json={"name": "Acme"})
        organization_id = org_response.json()["id"]

        user_response = await client.post(
            "/users",
            json={"name": "Jane Doe", "email": "jane@example.com"},
        )
        user_id = user_response.json()["id"]

        # Create first membership
        create_response1 = await client.post(
            "/memberships",
            json={"user_id": user_id, "organization_id": organization_id},
        )
        assert create_response1.status_code == HTTPStatus.CREATED

        # Try to create duplicate membership
        create_response2 = await client.post(
            "/memberships",
            json={"user_id": user_id, "organization_id": organization_id},
        )
        # Should fail with unique constraint violation
        assert create_response2.status_code in (
            HTTPStatus.BAD_REQUEST,
            HTTPStatus.CONFLICT,
        )

    @pytest.mark.asyncio
    async def test_create_membership_nonexistent_user(self, client: AsyncClient) -> None:
        """Creating membership with nonexistent user should fail."""
        # Create organization
        org_response = await client.post("/organizations", json={"name": "Acme"})
        organization_id = org_response.json()["id"]

        # Try to create membership with fake user
        create_response = await client.post(
            "/memberships",
            json={
                "user_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                "organization_id": organization_id,
            },
        )
        assert create_response.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_create_membership_nonexistent_organization(self, client: AsyncClient) -> None:
        """Creating membership with nonexistent organization should fail."""
        # Create user
        user_response = await client.post(
            "/users",
            json={"name": "Jane Doe", "email": "jane@example.com"},
        )
        user_id = user_response.json()["id"]

        # Try to create membership with fake organization
        create_response = await client.post(
            "/memberships",
            json={
                "user_id": user_id,
                "organization_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
            },
        )
        assert create_response.status_code == HTTPStatus.BAD_REQUEST


class TestMembershipCascadeDelete:
    """Test cascade delete behavior for memberships."""

    @pytest.mark.asyncio
    async def test_cascade_delete_organization(self, client: AsyncClient) -> None:
        """Deleting organization should cascade delete memberships."""
        # Create organization and user
        org_response = await client.post("/organizations", json={"name": "Acme"})
        organization_id = org_response.json()["id"]

        user_response = await client.post(
            "/users",
            json={"name": "Jane Doe", "email": "jane@example.com"},
        )
        user_id = user_response.json()["id"]

        # Create membership
        await client.post(
            "/memberships",
            json={"user_id": user_id, "organization_id": organization_id},
        )

        # Delete organization
        delete_org = await client.delete(f"/organizations/{organization_id}")
        assert delete_org.status_code == HTTPStatus.NO_CONTENT

        # Verify membership is cascade deleted
        list_response = await client.get("/memberships")
        assert list_response.status_code == HTTPStatus.OK
        # Check that the membership for the created org is deleted
        # (but fixture membership in default org will still exist)
        items = list_response.json()["items"]
        org_items = [item for item in items if item["organization_id"] == organization_id]
        assert org_items == []

        # Verify user still exists
        user_get = await client.get(f"/users/{user_id}")
        assert user_get.status_code == HTTPStatus.OK

    @pytest.mark.asyncio
    async def test_cascade_delete_user(self, client: AsyncClient) -> None:
        """Deleting user should cascade delete memberships.

        Note: POST /organizations auto-creates OWNER membership for the current
        user (default test user). So the org will have memberships for:
        1. Default test user (OWNER, auto-created)
        2. Jane (added explicitly)

        After deleting Jane, only the default test user's membership remains.
        """
        # Create organization (auto-creates OWNER membership for default test user)
        org_response = await client.post("/organizations", json={"name": "Acme"})
        organization_id = org_response.json()["id"]

        user_response = await client.post(
            "/users",
            json={"name": "Jane Doe", "email": "jane@example.com"},
        )
        user_id = user_response.json()["id"]

        # Create membership for Jane
        await client.post(
            "/memberships",
            json={"user_id": user_id, "organization_id": organization_id},
        )

        # Delete user Jane (pass X-User-ID header matching the user being deleted)
        delete_user = await client.delete(
            f"/users/{user_id}",
            headers={"X-User-ID": str(user_id), "X-Email": "jane@example.com"},
        )
        assert delete_user.status_code == HTTPStatus.NO_CONTENT

        # Verify Jane's membership is cascade deleted
        list_response = await client.get("/memberships")
        assert list_response.status_code == HTTPStatus.OK
        # Check that Jane's membership for the org is deleted
        # Note: The org still has the default test user's OWNER membership
        items = list_response.json()["items"]
        jane_memberships = [
            item for item in items if item["organization_id"] == organization_id and item["user_id"] == user_id
        ]
        assert jane_memberships == []

        # Verify organization still exists
        org_get = await client.get(f"/organizations/{organization_id}")
        assert org_get.status_code == HTTPStatus.OK


class TestMembershipErrorHandling:
    """Test membership error scenarios."""

    @pytest.mark.asyncio
    async def test_delete_nonexistent_membership(self, client: AsyncClient) -> None:
        """Deleting nonexistent membership should return 404."""
        response = await client.delete("/memberships/ffffffff-ffff-ffff-ffff-ffffffffffff")
        assert response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_create_membership_invalid_uuid(self, client: AsyncClient) -> None:
        """Creating membership with invalid UUIDs should fail."""
        # Create valid organization
        org_response = await client.post("/organizations", json={"name": "Acme"})
        organization_id = org_response.json()["id"]

        # Try to create with invalid user UUID
        response = await client.post(
            "/memberships",
            json={
                "user_id": "not-a-uuid",
                "organization_id": organization_id,
            },
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
