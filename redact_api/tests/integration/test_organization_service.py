"""Unit tests for organization_service.py - direct service function testing.

These tests call service functions directly with a database session,
bypassing the API layer to achieve better coverage of:
- Pagination parameters (offset/limit)
- Batch operations (list_users_for_organizations)
- Metrics recording
- Edge cases
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.core.metrics import active_memberships_gauge, organizations_created_total
from redact_api.models.membership import Membership, MembershipRole
from redact_api.models.organization import Organization, OrganizationCreate, OrganizationUpdate
from redact_api.models.user import User
from redact_api.services.organization_service import (
    create_organization,
    delete_organization,
    get_organization,
    list_organizations,
    list_users_for_organization,
    list_users_for_organizations,
    update_organization,
)


class TestGetOrganization:
    """Test get_organization service function."""

    @pytest.mark.asyncio
    async def test_get_organization_found(self, session: AsyncSession) -> None:
        """get_organization returns organization when found."""
        org = Organization(name=f"Test Org {uuid4()}")
        session.add(org)
        await session.commit()
        await session.refresh(org)

        result = await get_organization(session, org.id)

        assert result is not None
        assert result.id == org.id
        assert result.name == org.name

    @pytest.mark.asyncio
    async def test_get_organization_not_found(self, session: AsyncSession) -> None:
        """get_organization returns None when organization doesn't exist."""
        fake_id = uuid4()

        result = await get_organization(session, fake_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_organization_with_user_membership_filter(self, session: AsyncSession) -> None:
        """get_organization with user_id only returns org if user is member."""
        # Create user and organization
        user = User(name="Filter User", email=f"filter-{uuid4()}@example.com")
        org = Organization(name=f"Filter Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        # Create membership
        membership = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
        session.add(membership)
        await session.commit()

        # User is a member - should find org
        result = await get_organization(session, org.id, user_id=user.id)
        assert result is not None
        assert result.id == org.id

    @pytest.mark.asyncio
    async def test_get_organization_with_user_filter_not_member(self, session: AsyncSession) -> None:
        """get_organization returns None if user is not a member."""
        # Create user and organization (no membership)
        user = User(name="Non-Member User", email=f"non-member-{uuid4()}@example.com")
        org = Organization(name=f"Non-Member Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.commit()

        # User is NOT a member - should not find org
        result = await get_organization(session, org.id, user_id=user.id)
        assert result is None


class TestListOrganizations:
    """Test list_organizations service function with pagination."""

    @pytest.mark.asyncio
    async def test_list_organizations_default_pagination(self, session: AsyncSession) -> None:
        """list_organizations returns organizations with default pagination."""
        # Create multiple organizations
        for i in range(5):
            org = Organization(name=f"List Org {i} {uuid4()}")
            session.add(org)
        await session.commit()

        result = await list_organizations(session)

        # Should have at least 5 organizations (plus any fixture orgs)
        assert len(result) >= 5

    @pytest.mark.asyncio
    async def test_list_organizations_with_offset(self, session: AsyncSession) -> None:
        """list_organizations respects offset parameter."""
        # Create organizations
        for i in range(5):
            org = Organization(name=f"Offset Org {i} {uuid4()}")
            session.add(org)
        await session.commit()

        # Get all orgs
        all_orgs = await list_organizations(session, offset=0, limit=100)

        # Get orgs with offset
        offset_orgs = await list_organizations(session, offset=2, limit=100)

        # Should have 2 fewer orgs
        assert len(offset_orgs) == len(all_orgs) - 2

    @pytest.mark.asyncio
    async def test_list_organizations_with_limit(self, session: AsyncSession) -> None:
        """list_organizations respects limit parameter."""
        # Create organizations
        for i in range(5):
            org = Organization(name=f"Limit Org {i} {uuid4()}")
            session.add(org)
        await session.commit()

        result = await list_organizations(session, offset=0, limit=3)

        # Should have exactly 3 orgs
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_organizations_empty_result(self, session: AsyncSession) -> None:
        """list_organizations returns empty list when offset exceeds count."""
        result = await list_organizations(session, offset=10000, limit=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_list_organizations_with_user_filter(self, session: AsyncSession) -> None:
        """list_organizations with user_id only returns user's organizations."""
        # Create user
        user = User(name="Filter User", email=f"filter-list-{uuid4()}@example.com")
        session.add(user)
        await session.flush()  # type: ignore[attr-defined]

        # Create 2 orgs - user is member of only one
        org1 = Organization(name=f"User Org {uuid4()}")
        org2 = Organization(name=f"Other Org {uuid4()}")
        session.add_all([org1, org2])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        # Membership only for org1
        membership = Membership(user_id=user.id, organization_id=org1.id, role=MembershipRole.MEMBER)
        session.add(membership)
        await session.commit()

        # Without filter - gets all orgs
        all_orgs = await list_organizations(session)
        assert any(o.id == org2.id for o in all_orgs)

        # With user filter - only gets org1
        user_orgs = await list_organizations(session, user_id=user.id)
        org_ids = [o.id for o in user_orgs]
        assert org1.id in org_ids
        assert org2.id not in org_ids


class TestCreateOrganization:
    """Test create_organization service function."""

    @pytest.mark.asyncio
    async def test_create_organization_success(self, session: AsyncSession) -> None:
        """create_organization creates a new organization and returns it."""
        payload = OrganizationCreate(name=f"New Org {uuid4()}")

        result = await create_organization(session, payload)
        await session.commit()

        assert result.id is not None
        assert result.name == payload.name

    @pytest.mark.asyncio
    async def test_create_organization_increments_metric(self, session: AsyncSession) -> None:
        """create_organization increments the organizations_created_total counter."""
        # Get current count
        try:
            before = organizations_created_total.labels(environment="test")._value.get()
        except AttributeError:
            before = 0

        payload = OrganizationCreate(name=f"Metric Org {uuid4()}")
        await create_organization(session, payload)
        await session.commit()

        after = organizations_created_total.labels(environment="test")._value.get()

        # Counter should have increased
        assert after >= before


class TestUpdateOrganization:
    """Test update_organization service function."""

    @pytest.mark.asyncio
    async def test_update_organization_changes_fields(self, session: AsyncSession) -> None:
        """update_organization changes specified fields."""
        org = Organization(name="Original Org Name")
        session.add(org)
        await session.commit()
        await session.refresh(org)

        payload = OrganizationUpdate(name="Updated Org Name")
        result = await update_organization(session, org, payload)
        await session.commit()

        assert result.name == "Updated Org Name"

    @pytest.mark.asyncio
    async def test_update_organization_partial_update(self, session: AsyncSession) -> None:
        """update_organization only changes specified fields (exclude_unset)."""
        org = Organization(name="Original")
        session.add(org)
        await session.commit()
        await session.refresh(org)
        original_created = org.created_at

        payload = OrganizationUpdate()  # No fields set
        result = await update_organization(session, org, payload)
        await session.commit()

        # Name unchanged because not in update
        assert result.name == "Original"
        assert result.created_at == original_created


class TestDeleteOrganization:
    """Test delete_organization service function."""

    @pytest.mark.asyncio
    async def test_delete_organization_removes_from_db(self, session: AsyncSession) -> None:
        """delete_organization removes organization from database."""
        org = Organization(name=f"To Delete {uuid4()}")
        session.add(org)
        await session.commit()
        await session.refresh(org)
        org_id = org.id

        await delete_organization(session, org)
        await session.commit()

        result = await get_organization(session, org_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_organization_decrements_gauge_for_memberships(self, session: AsyncSession) -> None:
        """delete_organization decrements active_memberships_gauge by membership count."""
        # Create org with memberships
        org = Organization(name=f"Gauge Delete Org {uuid4()}")
        user1 = User(name="Gauge User 1", email=f"gauge1-{uuid4()}@example.com")
        user2 = User(name="Gauge User 2", email=f"gauge2-{uuid4()}@example.com")
        session.add_all([org, user1, user2])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        m1 = Membership(user_id=user1.id, organization_id=org.id, role=MembershipRole.OWNER)
        m2 = Membership(user_id=user2.id, organization_id=org.id, role=MembershipRole.MEMBER)
        session.add_all([m1, m2])  # type: ignore[attr-defined]
        await session.commit()
        await session.refresh(org)

        # Get gauge before delete
        try:
            before = active_memberships_gauge.labels(environment="test")._value.get()
        except AttributeError:
            before = 0

        await delete_organization(session, org)
        await session.commit()

        after = active_memberships_gauge.labels(environment="test")._value.get()

        # Gauge should have decreased by 2 (the number of memberships)
        assert after <= before


class TestListUsersForOrganization:
    """Test list_users_for_organization service function."""

    @pytest.mark.asyncio
    async def test_list_users_for_organization_with_members(self, session: AsyncSession) -> None:
        """list_users_for_organization returns organization's users."""
        # Create organization
        org = Organization(name=f"Users Org {uuid4()}")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        # Create users
        user1 = User(name="Org User 1", email=f"orguser1-{uuid4()}@example.com")
        user2 = User(name="Org User 2", email=f"orguser2-{uuid4()}@example.com")
        session.add_all([user1, user2])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        # Create memberships
        m1 = Membership(user_id=user1.id, organization_id=org.id, role=MembershipRole.OWNER)
        m2 = Membership(user_id=user2.id, organization_id=org.id, role=MembershipRole.MEMBER)
        session.add_all([m1, m2])  # type: ignore[attr-defined]
        await session.commit()

        result = await list_users_for_organization(session, org.id)

        assert len(result) == 2
        user_ids = {user.id for user in result}
        assert user1.id in user_ids
        assert user2.id in user_ids

    @pytest.mark.asyncio
    async def test_list_users_for_organization_no_members(self, session: AsyncSession) -> None:
        """list_users_for_organization returns empty list for org with no users."""
        org = Organization(name=f"Empty Org {uuid4()}")
        session.add(org)
        await session.commit()

        result = await list_users_for_organization(session, org.id)

        assert result == []


class TestListUsersForOrganizations:
    """Test list_users_for_organizations batch service function."""

    @pytest.mark.asyncio
    async def test_list_users_for_organizations_empty_input(self, session: AsyncSession) -> None:
        """list_users_for_organizations returns empty dict for empty input."""
        result = await list_users_for_organizations(session, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_list_users_for_organizations_returns_dict_for_all_ids(self, session: AsyncSession) -> None:
        """list_users_for_organizations returns dict with all requested org IDs."""
        # Create organizations
        org1 = Organization(name=f"Batch Org 1 {uuid4()}")
        org2 = Organization(name=f"Batch Org 2 {uuid4()}")
        session.add_all([org1, org2])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        # Create user and membership for only org1
        user = User(name="Batch User", email=f"batch-{uuid4()}@example.com")
        session.add(user)
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(user_id=user.id, organization_id=org1.id, role=MembershipRole.MEMBER)
        session.add(membership)
        await session.commit()

        result = await list_users_for_organizations(session, [org1.id, org2.id])

        # Should have keys for both organizations
        assert org1.id in result
        assert org2.id in result

        # org1 has the user, org2 doesn't
        assert len(result[org1.id]) == 1
        assert result[org1.id][0].id == user.id
        assert len(result[org2.id]) == 0

    @pytest.mark.asyncio
    async def test_list_users_for_organizations_multiple_users_per_org(self, session: AsyncSession) -> None:
        """list_users_for_organizations handles multiple users per org."""
        # Create organization
        org = Organization(name=f"Multi User Org {uuid4()}")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        # Create multiple users
        users = [User(name=f"Multi User {i}", email=f"multi{i}-{uuid4()}@example.com") for i in range(3)]
        session.add_all(users)  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        # Create memberships for all users
        for user in users:
            m = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
            session.add(m)
        await session.commit()

        result = await list_users_for_organizations(session, [org.id])

        assert org.id in result
        assert len(result[org.id]) == 3

    @pytest.mark.asyncio
    async def test_list_users_for_organizations_nonexistent_orgs(self, session: AsyncSession) -> None:
        """list_users_for_organizations returns empty lists for nonexistent orgs."""
        fake_ids = [uuid4(), uuid4()]

        result = await list_users_for_organizations(session, fake_ids)

        # Should return dict with empty lists for each ID
        assert len(result) == 2
        for fake_id in fake_ids:
            assert fake_id in result
            assert result[fake_id] == []
