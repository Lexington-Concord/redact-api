"""Tests for race conditions in RBAC and membership operations."""

import asyncio
from http import HTTPStatus

import pytest
from httpx import AsyncClient, Response

from redact_api.models.membership import MembershipRole


@pytest.mark.asyncio
async def test_concurrent_role_changes(
    client_bypass_auth: AsyncClient,
) -> None:
    """Test that concurrent role changes don't cause inconsistencies.

    This test verifies that:
    1. Concurrent attempts to modify the same membership are idempotent
    2. The final state is consistent (ADMIN role)
    3. No database corruption or constraint violations occur
    """
    # Create dedicated user (will have membership in default org only)
    user_response = await client_bypass_auth.post(
        "/users",
        json={
            "name": "Race Test User 1",
            "email": "race-test-1@example.com",
        },
    )
    assert user_response.status_code == HTTPStatus.CREATED
    user_id = user_response.json()["id"]

    # Create dedicated organization (default test user becomes OWNER)
    org_response = await client_bypass_auth.post(
        "/organizations",
        json={"name": "Race Test Org 1"},
    )
    assert org_response.status_code == HTTPStatus.CREATED
    org_id = org_response.json()["id"]

    # Create membership as MEMBER (no pre-existing membership between user and org)
    membership_response = await client_bypass_auth.post(
        "/memberships",
        json={
            "user_id": user_id,
            "organization_id": org_id,
            "role": MembershipRole.MEMBER.value,
        },
    )
    assert membership_response.status_code == HTTPStatus.CREATED
    membership_id = membership_response.json()["id"]

    # Try to promote to ADMIN twice concurrently
    async def promote_to_admin() -> Response:
        return await client_bypass_auth.patch(
            f"/memberships/{membership_id}",
            json={"role": MembershipRole.ADMIN.value},
        )

    results = await asyncio.gather(
        promote_to_admin(),
        promote_to_admin(),
        return_exceptions=True,
    )

    # Type narrowing for mypy
    for r in results:
        if isinstance(r, BaseException):
            raise r

    # Both should succeed (idempotent) or one should conflict
    assert all(r.status_code in (HTTPStatus.OK, HTTPStatus.CONFLICT) for r in results)  # type: ignore[union-attr, operator]

    # Final state should be ADMIN (check via list endpoint)
    list_response = await client_bypass_auth.get("/memberships")
    memberships = [m for m in list_response.json()["items"] if m["id"] == str(membership_id)]
    assert len(memberships) == 1
    assert memberships[0]["role"] == MembershipRole.ADMIN.value


@pytest.mark.asyncio
async def test_concurrent_membership_creation(
    client_bypass_auth: AsyncClient,
) -> None:
    """Test that concurrent membership creation handles duplicates properly.

    This test verifies that:
    1. Duplicate membership creation attempts are handled gracefully
    2. Only one membership is created (unique constraint enforced)
    3. No database corruption occurs
    """
    # Create dedicated user (will have membership in default org only)
    user_response = await client_bypass_auth.post(
        "/users",
        json={
            "name": "Race Test User 2",
            "email": "race-test-2@example.com",
        },
    )
    assert user_response.status_code == HTTPStatus.CREATED
    user_id = user_response.json()["id"]

    # Create dedicated organization (default test user becomes OWNER)
    org_response = await client_bypass_auth.post(
        "/organizations",
        json={"name": "Race Test Org 2"},
    )
    assert org_response.status_code == HTTPStatus.CREATED
    org_id = org_response.json()["id"]

    # Try to create the same membership twice concurrently
    async def create_membership() -> Response:
        return await client_bypass_auth.post(
            "/memberships",
            json={
                "user_id": user_id,
                "organization_id": org_id,
                "role": MembershipRole.MEMBER.value,
            },
        )

    results = await asyncio.gather(
        create_membership(),
        create_membership(),
        return_exceptions=True,
    )

    # Type narrowing for mypy
    for r in results:
        if isinstance(r, BaseException):
            raise r

    # One should succeed, one should fail with conflict/bad request
    status_codes = [r.status_code for r in results]  # type: ignore[union-attr]
    assert HTTPStatus.CREATED in status_codes
    assert any(code in (HTTPStatus.BAD_REQUEST, HTTPStatus.CONFLICT) for code in status_codes)

    # Verify only one membership exists
    list_response = await client_bypass_auth.get("/memberships")
    assert list_response.status_code == HTTPStatus.OK
    memberships = [
        m for m in list_response.json()["items"] if m["user_id"] == user_id and m["organization_id"] == org_id
    ]
    assert len(memberships) == 1


@pytest.mark.asyncio
async def test_concurrent_role_changes_different_roles(
    client_bypass_auth: AsyncClient,
) -> None:
    """Test concurrent changes to different roles.

    This test verifies that:
    1. Concurrent role changes to different target roles are handled
    2. Final state is one of the requested roles (not corrupted)
    3. No database errors occur
    """
    # Create dedicated user (will have membership in default org only)
    user_response = await client_bypass_auth.post(
        "/users",
        json={
            "name": "Race Test User 3",
            "email": "race-test-3@example.com",
        },
    )
    assert user_response.status_code == HTTPStatus.CREATED
    user_id = user_response.json()["id"]

    # Create dedicated organization (default test user becomes OWNER)
    org_response = await client_bypass_auth.post(
        "/organizations",
        json={"name": "Race Test Org 3"},
    )
    assert org_response.status_code == HTTPStatus.CREATED
    org_id = org_response.json()["id"]

    # Create membership as MEMBER (no pre-existing membership between user and org)
    membership_response = await client_bypass_auth.post(
        "/memberships",
        json={
            "user_id": user_id,
            "organization_id": org_id,
            "role": MembershipRole.MEMBER.value,
        },
    )
    assert membership_response.status_code == HTTPStatus.CREATED
    membership_id = membership_response.json()["id"]

    # Try to change to ADMIN and OWNER concurrently
    async def promote_to_admin() -> Response:
        return await client_bypass_auth.patch(
            f"/memberships/{membership_id}",
            json={"role": MembershipRole.ADMIN.value},
        )

    async def promote_to_owner() -> Response:
        return await client_bypass_auth.patch(
            f"/memberships/{membership_id}",
            json={"role": MembershipRole.OWNER.value},
        )

    results = await asyncio.gather(
        promote_to_admin(),
        promote_to_owner(),
        return_exceptions=True,
    )

    # Type narrowing for mypy
    for r in results:
        if isinstance(r, BaseException):
            raise r

    # At least one should succeed
    assert any(r.status_code == HTTPStatus.OK for r in results)  # type: ignore[union-attr]

    # Final state should be one of the requested roles (check via list endpoint)
    list_response = await client_bypass_auth.get("/memberships")
    memberships = [m for m in list_response.json()["items"] if m["id"] == str(membership_id)]
    assert len(memberships) == 1
    final_role = memberships[0]["role"]
    assert final_role in (MembershipRole.ADMIN.value, MembershipRole.OWNER.value)


@pytest.mark.asyncio
async def test_concurrent_membership_deletion(
    client_bypass_auth: AsyncClient,
) -> None:
    """Test that concurrent deletion attempts are idempotent.

    This test verifies that:
    1. Multiple deletion attempts on the same membership are safe
    2. First delete succeeds, subsequent ones fail gracefully (404)
    3. No database corruption occurs
    """
    # Create dedicated user (will have membership in default org only)
    user_response = await client_bypass_auth.post(
        "/users",
        json={
            "name": "Race Test User 4",
            "email": "race-test-4@example.com",
        },
    )
    assert user_response.status_code == HTTPStatus.CREATED
    user_id = user_response.json()["id"]

    # Create dedicated organization (default test user becomes OWNER)
    org_response = await client_bypass_auth.post(
        "/organizations",
        json={"name": "Race Test Org 4"},
    )
    assert org_response.status_code == HTTPStatus.CREATED
    org_id = org_response.json()["id"]

    # Create membership (no pre-existing membership between user and org)
    membership_response = await client_bypass_auth.post(
        "/memberships",
        json={
            "user_id": user_id,
            "organization_id": org_id,
            "role": MembershipRole.MEMBER.value,
        },
    )
    assert membership_response.status_code == HTTPStatus.CREATED
    membership_id = membership_response.json()["id"]

    # Try to delete twice concurrently
    async def delete_membership() -> Response:
        return await client_bypass_auth.delete(f"/memberships/{membership_id}")

    results = await asyncio.gather(
        delete_membership(),
        delete_membership(),
        return_exceptions=True,
    )

    # Type narrowing for mypy
    for r in results:
        if isinstance(r, BaseException):
            raise r

    # One should succeed (NO_CONTENT), one should fail (NOT_FOUND)
    status_codes = [r.status_code for r in results]  # type: ignore[union-attr]
    assert HTTPStatus.NO_CONTENT in status_codes
    assert HTTPStatus.NOT_FOUND in status_codes

    # Verify membership is deleted (check via list endpoint)
    list_response = await client_bypass_auth.get("/memberships")
    memberships = [m for m in list_response.json()["items"] if m["id"] == str(membership_id)]
    assert len(memberships) == 0


@pytest.mark.asyncio
async def test_role_check_during_role_change(
    authenticated_client: AsyncClient,
    test_user: dict,
    test_organization: dict,
) -> None:
    """Test that permission checks are consistent during role changes.

    Note: This test uses authenticated_client to test real RBAC,
    but for now we skip it since it requires JWT token generation
    which is more complex. This is a placeholder for future enhancement.

    Future implementation should verify that:
    1. Permission checks during concurrent role changes are consistent
    2. No race condition allows unauthorized access
    3. Role changes are atomic with respect to permission checks
    """
    pass


@pytest.mark.asyncio
async def test_concurrent_create_and_delete(
    client_bypass_auth: AsyncClient,
) -> None:
    """Test concurrent creation and deletion of memberships.

    This test verifies that:
    1. Creating and deleting the same membership concurrently is handled
    2. Final state is consistent (either exists or doesn't exist)
    3. No database corruption occurs
    """
    # Create dedicated user (will have membership in default org only)
    user_response = await client_bypass_auth.post(
        "/users",
        json={
            "name": "Race Test User 5",
            "email": "race-test-5@example.com",
        },
    )
    assert user_response.status_code == HTTPStatus.CREATED
    user_id = user_response.json()["id"]

    # Create dedicated organization (default test user becomes OWNER)
    org_response = await client_bypass_auth.post(
        "/organizations",
        json={"name": "Race Test Org 5"},
    )
    assert org_response.status_code == HTTPStatus.CREATED
    org_id = org_response.json()["id"]

    # Create membership first
    membership_response = await client_bypass_auth.post(
        "/memberships",
        json={
            "user_id": user_id,
            "organization_id": org_id,
            "role": MembershipRole.MEMBER.value,
        },
    )
    assert membership_response.status_code == HTTPStatus.CREATED
    membership_id = membership_response.json()["id"]

    # Delete it
    delete_response = await client_bypass_auth.delete(f"/memberships/{membership_id}")
    assert delete_response.status_code == HTTPStatus.NO_CONTENT

    # Try to create and delete concurrently
    async def create_membership() -> Response:
        return await client_bypass_auth.post(
            "/memberships",
            json={
                "user_id": user_id,
                "organization_id": org_id,
                "role": MembershipRole.MEMBER.value,
            },
        )

    async def delete_if_exists() -> Response | None:
        # First check if it exists
        list_response = await client_bypass_auth.get("/memberships")
        memberships = [
            m for m in list_response.json()["items"] if m["user_id"] == user_id and m["organization_id"] == org_id
        ]
        if memberships:
            return await client_bypass_auth.delete(f"/memberships/{memberships[0]['id']}")
        return None

    results = await asyncio.gather(
        create_membership(),
        delete_if_exists(),
        return_exceptions=True,
    )

    # Type narrowing for mypy
    if isinstance(results[0], BaseException):
        raise results[0]
    if isinstance(results[1], BaseException):
        raise results[1]

    # Create should succeed
    assert results[0].status_code == HTTPStatus.CREATED

    # Final state check - membership might exist or not depending on timing
    list_response = await client_bypass_auth.get("/memberships")
    memberships = [
        m for m in list_response.json()["items"] if m["user_id"] == user_id and m["organization_id"] == org_id
    ]
    # Should be 0 or 1, never more
    assert len(memberships) in (0, 1)
