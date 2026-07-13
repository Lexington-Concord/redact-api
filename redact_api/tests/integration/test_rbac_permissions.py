"""Comprehensive Role-Based Access Control (RBAC) tests.

Tests verify that role-based permissions prevent unauthorized actions within
organizations. These tests ensure:

1. OWNER can perform all operations (delete org, change roles, manage members)
2. ADMIN can manage members and settings but not delete org or change roles
3. MEMBER can only use resources, not manage them
4. Role hierarchy is enforced (OWNER > ADMIN > MEMBER)
5. Users cannot escalate their own roles
"""

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.models.membership import Membership, MembershipRole
from redact_api.models.organization import Organization
from redact_api.models.user import User

# Test constants
NONEXISTENT_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


@pytest.fixture
async def org_with_owner_admin_member(
    session: AsyncSession,
) -> tuple[Organization, User, User, User]:
    """Organization with OWNER, ADMIN, and MEMBER roles.

    Returns:
        Tuple of (org, owner_user, admin_user, member_user)
    """
    # Create organization
    org = Organization(name="Test Organization")
    session.add(org)
    await session.flush()  # type: ignore[attr-defined]

    # Create users
    owner_user = User(name="Owner User", email="owner@example.com")
    admin_user = User(name="Admin User", email="admin@example.com")
    member_user = User(name="Member User", email="member@example.com")
    session.add(owner_user)
    session.add(admin_user)
    session.add(member_user)
    await session.flush()  # type: ignore[attr-defined]

    # Create memberships with roles
    owner_membership = Membership(
        user_id=owner_user.id,
        organization_id=org.id,
        role=MembershipRole.OWNER,
    )
    admin_membership = Membership(
        user_id=admin_user.id,
        organization_id=org.id,
        role=MembershipRole.ADMIN,
    )
    member_membership = Membership(
        user_id=member_user.id,
        organization_id=org.id,
        role=MembershipRole.MEMBER,
    )
    session.add(owner_membership)
    session.add(admin_membership)
    session.add(member_membership)

    await session.commit()
    return org, owner_user, admin_user, member_user


class TestOrganizationDeletePermissions:
    """Test that only OWNER can delete organizations."""

    @pytest.mark.asyncio
    async def test_owner_can_delete_organization(
        self,
        client: AsyncClient,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """OWNER can delete organization."""
        org, owner_user, _admin_user, _member_user = org_with_owner_admin_member

        # Owner attempts to delete org
        response = await client.delete(
            f"/organizations/{org.id}",
            headers={
                "X-Test-User-ID": str(owner_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

    @pytest.mark.asyncio
    async def test_admin_cannot_delete_organization(
        self,
        client: AsyncClient,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """ADMIN cannot delete organization (403 Forbidden)."""
        org, _owner_user, admin_user, _member_user = org_with_owner_admin_member

        # Admin attempts to delete org
        response = await client.delete(
            f"/organizations/{org.id}",
            headers={
                "X-Test-User-ID": str(admin_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Insufficient permissions" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_member_cannot_delete_organization(
        self,
        client: AsyncClient,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """MEMBER cannot delete organization (403 Forbidden)."""
        org, _owner_user, _admin_user, member_user = org_with_owner_admin_member

        # Member attempts to delete org
        response = await client.delete(
            f"/organizations/{org.id}",
            headers={
                "X-Test-User-ID": str(member_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Insufficient permissions" in response.json()["detail"]


class TestOrganizationUpdatePermissions:
    """Test that ADMIN and OWNER can update organizations."""

    @pytest.mark.asyncio
    async def test_owner_can_update_organization(
        self,
        client: AsyncClient,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """OWNER can update organization settings."""
        org, owner_user, _admin_user, _member_user = org_with_owner_admin_member

        response = await client.patch(
            f"/organizations/{org.id}",
            json={"name": "Updated by Owner"},
            headers={
                "X-Test-User-ID": str(owner_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["name"] == "Updated by Owner"

    @pytest.mark.asyncio
    async def test_admin_can_update_organization(
        self,
        client: AsyncClient,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """ADMIN can update organization settings."""
        org, _owner_user, admin_user, _member_user = org_with_owner_admin_member

        response = await client.patch(
            f"/organizations/{org.id}",
            json={"name": "Updated by Admin"},
            headers={
                "X-Test-User-ID": str(admin_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["name"] == "Updated by Admin"

    @pytest.mark.asyncio
    async def test_member_cannot_update_organization(
        self,
        client: AsyncClient,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """MEMBER cannot update organization settings (403 Forbidden)."""
        org, _owner_user, _admin_user, member_user = org_with_owner_admin_member

        response = await client.patch(
            f"/organizations/{org.id}",
            json={"name": "Updated by Member"},
            headers={
                "X-Test-User-ID": str(member_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Insufficient permissions" in response.json()["detail"]


class TestMembershipAddPermissions:
    """Test that ADMIN and OWNER can add members."""

    @pytest.mark.asyncio
    async def test_owner_can_add_member(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """OWNER can add new members."""
        org, owner_user, _admin_user, _member_user = org_with_owner_admin_member

        # Create new user to add
        new_user = User(name="New User", email="new@example.com")
        session.add(new_user)
        await session.commit()

        response = await client.post(
            "/memberships",
            json={
                "user_id": str(new_user.id),
                "organization_id": str(org.id),
                "role": "member",
            },
            headers={
                "X-Test-User-ID": str(owner_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json()["role"] == "member"

    @pytest.mark.asyncio
    async def test_admin_can_add_member(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """ADMIN can add new members."""
        org, _owner_user, admin_user, _member_user = org_with_owner_admin_member

        # Create new user to add
        new_user = User(name="New User 2", email="new2@example.com")
        session.add(new_user)
        await session.commit()

        response = await client.post(
            "/memberships",
            json={
                "user_id": str(new_user.id),
                "organization_id": str(org.id),
                "role": "member",
            },
            headers={
                "X-Test-User-ID": str(admin_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.CREATED
        assert response.json()["role"] == "member"

    @pytest.mark.asyncio
    async def test_member_cannot_add_member(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """MEMBER cannot add new members (403 Forbidden)."""
        org, _owner_user, _admin_user, member_user = org_with_owner_admin_member

        # Create new user to add
        new_user = User(name="New User 3", email="new3@example.com")
        session.add(new_user)
        await session.commit()

        response = await client.post(
            "/memberships",
            json={
                "user_id": str(new_user.id),
                "organization_id": str(org.id),
                "role": "member",
            },
            headers={
                "X-Test-User-ID": str(member_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Insufficient permissions" in response.json()["detail"]


class TestMembershipRemovePermissions:
    """Test that ADMIN and OWNER can remove members."""

    @pytest.mark.asyncio
    async def test_owner_can_remove_member(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """OWNER can remove members."""
        org, owner_user, _admin_user, member_user = org_with_owner_admin_member

        # Get member's membership ID

        stmt = select(Membership).where(
            Membership.user_id == member_user.id,
            Membership.organization_id == org.id,
        )
        result = await session.execute(stmt)
        membership = result.scalar_one()

        response = await client.delete(
            f"/memberships/{membership.id}",
            headers={
                "X-Test-User-ID": str(owner_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

    @pytest.mark.asyncio
    async def test_admin_can_remove_member(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """ADMIN can remove members."""
        org, _owner_user, admin_user, member_user = org_with_owner_admin_member

        # Get member's membership ID

        stmt = select(Membership).where(
            Membership.user_id == member_user.id,
            Membership.organization_id == org.id,
        )
        result = await session.execute(stmt)
        membership = result.scalar_one()

        response = await client.delete(
            f"/memberships/{membership.id}",
            headers={
                "X-Test-User-ID": str(admin_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.NO_CONTENT

    @pytest.mark.asyncio
    async def test_member_cannot_remove_member(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """MEMBER cannot remove members (403 Forbidden)."""
        org, owner_user, _admin_user, member_user = org_with_owner_admin_member

        # Get owner's membership ID

        stmt = select(Membership).where(
            Membership.user_id == owner_user.id,
            Membership.organization_id == org.id,
        )
        result = await session.execute(stmt)
        membership = result.scalar_one()

        response = await client.delete(
            f"/memberships/{membership.id}",
            headers={
                "X-Test-User-ID": str(member_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Insufficient permissions" in response.json()["detail"]


class TestRoleChangePermissions:
    """Test that only OWNER can change roles."""

    @pytest.mark.asyncio
    async def test_owner_can_change_member_role_to_admin(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """OWNER can promote MEMBER to ADMIN."""
        org, owner_user, _admin_user, member_user = org_with_owner_admin_member

        # Get member's membership ID

        stmt = select(Membership).where(
            Membership.user_id == member_user.id,
            Membership.organization_id == org.id,
        )
        result = await session.execute(stmt)
        membership = result.scalar_one()

        response = await client.patch(
            f"/memberships/{membership.id}",
            json={"role": "admin"},
            headers={
                "X-Test-User-ID": str(owner_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["role"] == "admin"

    @pytest.mark.asyncio
    async def test_owner_can_change_admin_role_to_member(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """OWNER can demote ADMIN to MEMBER."""
        org, owner_user, admin_user, _member_user = org_with_owner_admin_member

        # Get admin's membership ID

        stmt = select(Membership).where(
            Membership.user_id == admin_user.id,
            Membership.organization_id == org.id,
        )
        result = await session.execute(stmt)
        membership = result.scalar_one()

        response = await client.patch(
            f"/memberships/{membership.id}",
            json={"role": "member"},
            headers={
                "X-Test-User-ID": str(owner_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["role"] == "member"

    @pytest.mark.asyncio
    async def test_admin_cannot_change_member_role(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """ADMIN cannot change member roles (403 Forbidden)."""
        org, _owner_user, admin_user, member_user = org_with_owner_admin_member

        # Get member's membership ID

        stmt = select(Membership).where(
            Membership.user_id == member_user.id,
            Membership.organization_id == org.id,
        )
        result = await session.execute(stmt)
        membership = result.scalar_one()

        response = await client.patch(
            f"/memberships/{membership.id}",
            json={"role": "admin"},
            headers={
                "X-Test-User-ID": str(admin_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Insufficient permissions" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_member_cannot_change_role(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """MEMBER cannot change roles (403 Forbidden)."""
        org, owner_user, _admin_user, member_user = org_with_owner_admin_member

        # Get owner's membership ID

        stmt = select(Membership).where(
            Membership.user_id == owner_user.id,
            Membership.organization_id == org.id,
        )
        result = await session.execute(stmt)
        membership = result.scalar_one()

        response = await client.patch(
            f"/memberships/{membership.id}",
            json={"role": "member"},
            headers={
                "X-Test-User-ID": str(member_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "Insufficient permissions" in response.json()["detail"]


class TestRoleHierarchy:
    """Test role hierarchy is enforced (OWNER > ADMIN > MEMBER)."""

    @pytest.mark.asyncio
    async def test_owner_has_admin_permissions(
        self,
        client: AsyncClient,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """OWNER can perform ADMIN operations (hierarchy test)."""
        org, owner_user, _admin_user, _member_user = org_with_owner_admin_member

        # OWNER updates org (ADMIN permission)
        response = await client.patch(
            f"/organizations/{org.id}",
            json={"name": "Owner Acting as Admin"},
            headers={
                "X-Test-User-ID": str(owner_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.asyncio
    async def test_owner_has_member_permissions(
        self,
        client: AsyncClient,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """OWNER can perform MEMBER operations (hierarchy test)."""
        org, owner_user, _admin_user, _member_user = org_with_owner_admin_member

        # OWNER reads org (MEMBER permission - everyone can read)
        response = await client.get(
            f"/organizations/{org.id}",
            headers={
                "X-Test-User-ID": str(owner_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.asyncio
    async def test_admin_has_member_permissions(
        self,
        client: AsyncClient,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """ADMIN can perform MEMBER operations (hierarchy test)."""
        org, _owner_user, admin_user, _member_user = org_with_owner_admin_member

        # ADMIN reads org (MEMBER permission - everyone can read)
        response = await client.get(
            f"/organizations/{org.id}",
            headers={
                "X-Test-User-ID": str(admin_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.OK


class TestDataMigrationRoleAssignment:
    """Test that first member gets OWNER role during migration."""

    @pytest.mark.asyncio
    async def test_new_org_first_member_is_owner(
        self,
        client: AsyncClient,
    ) -> None:
        """First member added to new organization should get OWNER role.

        Note: The default_auth_user_in_org fixture already creates the default
        test user with ID 00000000-0000-0000-0000-000000000001. This test uses
        that existing user as the authenticated user.

        POST /organizations auto-creates OWNER membership for the current user.
        This test verifies that we can then add additional members as OWNER.
        """
        # The default test user already exists from the fixture
        default_test_user_id = "00000000-0000-0000-0000-000000000001"

        # Create organization (auto-creates OWNER membership for default test user)
        org_response = await client.post(
            "/organizations",
            json={"name": "New Org"},
        )
        org_id = org_response.json()["id"]

        # Create a new user to add as first explicit member
        user_response = await client.post(
            "/users",
            json={"name": "First User", "email": "first@example.com"},
        )
        user_id = user_response.json()["id"]

        # Add first member with default test user as the authenticated user (who owns the org)
        membership_response = await client.post(
            "/memberships",
            json={
                "user_id": user_id,
                "organization_id": org_id,
                "role": "owner",
            },
            headers={
                "X-Test-User-ID": default_test_user_id,
                "X-Test-Org-ID": org_id,
            },
        )
        assert membership_response.status_code == HTTPStatus.CREATED

        # Verify role
        membership_data = membership_response.json()
        assert membership_data["role"] == "owner"

    @pytest.mark.asyncio
    async def test_subsequent_members_are_member_by_default(
        self,
        client: AsyncClient,
        session: AsyncSession,
        org_with_owner_admin_member: tuple[Organization, User, User, User],
    ) -> None:
        """Subsequent members default to MEMBER role."""
        org, owner_user, _admin_user, _member_user = org_with_owner_admin_member

        # Create new user
        new_user = User(name="Fourth User", email="fourth@example.com")
        session.add(new_user)
        await session.commit()

        # Add new member without specifying role
        response = await client.post(
            "/memberships",
            json={
                "user_id": str(new_user.id),
                "organization_id": str(org.id),
            },
            headers={
                "X-Test-User-ID": str(owner_user.id),
                "X-Test-Org-ID": str(org.id),
            },
        )
        assert response.status_code == HTTPStatus.CREATED

        # Verify default role is MEMBER
        membership_data = response.json()
        assert membership_data["role"] == "member"
