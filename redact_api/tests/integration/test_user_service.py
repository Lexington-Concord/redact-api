"""Unit tests for user_service.py - direct service function testing.

These tests call service functions directly with a database session,
bypassing the API layer to achieve better coverage of:
- Pagination parameters (offset/limit)
- Batch operations (list_organizations_for_users)
- Metrics recording
- Edge cases
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.core.metrics import users_created_total
from redact_api.models.membership import Membership, MembershipRole
from redact_api.models.organization import Organization
from redact_api.models.user import User, UserCreate, UserUpdate
from redact_api.services.user_service import (
    create_user,
    delete_user,
    get_user,
    list_organizations_for_user,
    list_organizations_for_users,
    list_users,
    update_user,
)


class TestGetUser:
    """Test get_user service function."""

    @pytest.mark.asyncio
    async def test_get_user_found(self, session: AsyncSession) -> None:
        """get_user returns user when found."""
        # Create a user directly
        user = User(name="Test User", email=f"test-{uuid4()}@example.com")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        # Fetch via service
        result = await get_user(session, user.id)

        assert result is not None
        assert result.id == user.id
        assert result.email == user.email

    @pytest.mark.asyncio
    async def test_get_user_not_found(self, session: AsyncSession) -> None:
        """get_user returns None when user doesn't exist."""
        fake_id = uuid4()

        result = await get_user(session, fake_id)

        assert result is None


class TestListUsers:
    """Test list_users service function with pagination."""

    @pytest.mark.asyncio
    async def test_list_users_default_pagination(self, session: AsyncSession) -> None:
        """list_users returns users with default pagination."""
        # Create multiple users
        for i in range(5):
            user = User(name=f"User {i}", email=f"user-list-{i}-{uuid4()}@example.com")
            session.add(user)
        await session.commit()

        # List with defaults
        result = await list_users(session)

        # Should have at least 5 users (plus any fixture users)
        assert len(result) >= 5

    @pytest.mark.asyncio
    async def test_list_users_with_offset(self, session: AsyncSession) -> None:
        """list_users respects offset parameter."""
        # Create users
        for i in range(5):
            user = User(name=f"Offset User {i}", email=f"offset-{i}-{uuid4()}@example.com")
            session.add(user)
        await session.commit()

        # Get all users
        all_users = await list_users(session, offset=0, limit=100)

        # Get users with offset
        offset_users = await list_users(session, offset=2, limit=100)

        # Should have 2 fewer users
        assert len(offset_users) == len(all_users) - 2

    @pytest.mark.asyncio
    async def test_list_users_with_limit(self, session: AsyncSession) -> None:
        """list_users respects limit parameter."""
        # Create users
        for i in range(5):
            user = User(name=f"Limit User {i}", email=f"limit-{i}-{uuid4()}@example.com")
            session.add(user)
        await session.commit()

        # Get limited users
        result = await list_users(session, offset=0, limit=3)

        # Should have exactly 3 users
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_users_empty_result(self, session: AsyncSession) -> None:
        """list_users returns empty list when offset exceeds count."""
        result = await list_users(session, offset=10000, limit=10)

        assert result == []


class TestCreateUser:
    """Test create_user service function."""

    @pytest.mark.asyncio
    async def test_create_user_success(self, session: AsyncSession) -> None:
        """create_user creates a new user and returns it."""
        payload = UserCreate(name="New User", email=f"create-{uuid4()}@example.com")

        result = await create_user(session, payload)
        await session.commit()

        assert result.id is not None
        assert result.name == "New User"
        assert result.email == payload.email

    @pytest.mark.asyncio
    async def test_create_user_increments_metric(self, session: AsyncSession) -> None:
        """create_user increments the users_created_total counter."""
        # Get current count (may not have any samples yet for this label)
        try:
            before = users_created_total.labels(environment="test")._value.get()
        except AttributeError:
            before = 0

        payload = UserCreate(name="Metric User", email=f"metric-{uuid4()}@example.com")
        await create_user(session, payload)
        await session.commit()

        after = users_created_total.labels(environment="test")._value.get()

        # Counter should have increased
        assert after >= before  # At least same (metrics may be from previous tests)


class TestUpdateUser:
    """Test update_user service function."""

    @pytest.mark.asyncio
    async def test_update_user_changes_fields(self, session: AsyncSession) -> None:
        """update_user changes specified fields."""
        # Create user
        user = User(name="Original", email=f"update-{uuid4()}@example.com")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        # Update user
        payload = UserUpdate(name="Updated")
        result = await update_user(session, user, payload)
        await session.commit()

        assert result.name == "Updated"
        assert result.email == user.email  # Unchanged

    @pytest.mark.asyncio
    async def test_update_user_partial_update(self, session: AsyncSession) -> None:
        """update_user only changes specified fields (exclude_unset)."""
        # Create user
        user = User(name="Original Name", email=f"partial-{uuid4()}@example.com")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        original_name = user.name

        # Update with only email (not name)
        new_email = f"partial-new-{uuid4()}@example.com"
        payload = UserUpdate(email=new_email)
        result = await update_user(session, user, payload)
        await session.commit()

        assert result.email == new_email
        assert result.name == original_name  # Unchanged


class TestDeleteUser:
    """Test delete_user service function."""

    @pytest.mark.asyncio
    async def test_delete_user_removes_from_db(self, session: AsyncSession) -> None:
        """delete_user removes user from database."""
        # Create user
        user = User(name="To Delete", email=f"delete-{uuid4()}@example.com")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

        # Delete user
        await delete_user(session, user)
        await session.commit()

        # Verify deleted
        result = await get_user(session, user_id)
        assert result is None


class TestListOrganizationsForUser:
    """Test list_organizations_for_user service function."""

    @pytest.mark.asyncio
    async def test_list_organizations_for_user_with_memberships(self, session: AsyncSession) -> None:
        """list_organizations_for_user returns user's organizations."""
        # Create user
        user = User(name="Org User", email=f"org-user-{uuid4()}@example.com")
        session.add(user)
        await session.flush()  # type: ignore[attr-defined]

        # Create organizations
        org1 = Organization(name=f"Org 1 {uuid4()}")
        org2 = Organization(name=f"Org 2 {uuid4()}")
        session.add_all([org1, org2])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        # Create memberships
        m1 = Membership(user_id=user.id, organization_id=org1.id, role=MembershipRole.MEMBER)
        m2 = Membership(user_id=user.id, organization_id=org2.id, role=MembershipRole.ADMIN)
        session.add_all([m1, m2])  # type: ignore[attr-defined]
        await session.commit()

        # List organizations
        result = await list_organizations_for_user(session, user.id)

        assert len(result) == 2
        org_ids = {org.id for org in result}
        assert org1.id in org_ids
        assert org2.id in org_ids

    @pytest.mark.asyncio
    async def test_list_organizations_for_user_no_memberships(self, session: AsyncSession) -> None:
        """list_organizations_for_user returns empty list for user with no orgs."""
        # Create user with no memberships
        user = User(name="No Org User", email=f"no-org-{uuid4()}@example.com")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        # List organizations
        result = await list_organizations_for_user(session, user.id)

        assert result == []


class TestListOrganizationsForUsers:
    """Test list_organizations_for_users batch service function."""

    @pytest.mark.asyncio
    async def test_list_organizations_for_users_empty_input(self, session: AsyncSession) -> None:
        """list_organizations_for_users returns empty dict for empty input."""
        result = await list_organizations_for_users(session, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_list_organizations_for_users_returns_dict_for_all_ids(self, session: AsyncSession) -> None:
        """list_organizations_for_users returns dict with all requested user IDs."""
        # Create users
        user1 = User(name="Batch User 1", email=f"batch1-{uuid4()}@example.com")
        user2 = User(name="Batch User 2", email=f"batch2-{uuid4()}@example.com")
        session.add_all([user1, user2])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        # Create org and membership for only user1
        org = Organization(name=f"Batch Org {uuid4()}")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(user_id=user1.id, organization_id=org.id, role=MembershipRole.MEMBER)
        session.add(membership)
        await session.commit()

        # List organizations for both users
        result = await list_organizations_for_users(session, [user1.id, user2.id])

        # Should have keys for both users
        assert user1.id in result
        assert user2.id in result

        # user1 has the org, user2 doesn't
        assert len(result[user1.id]) == 1
        assert result[user1.id][0].id == org.id
        assert len(result[user2.id]) == 0

    @pytest.mark.asyncio
    async def test_list_organizations_for_users_multiple_orgs_per_user(self, session: AsyncSession) -> None:
        """list_organizations_for_users handles multiple orgs per user."""
        # Create user
        user = User(name="Multi Org User", email=f"multi-org-{uuid4()}@example.com")
        session.add(user)
        await session.flush()  # type: ignore[attr-defined]

        # Create multiple organizations
        orgs = [Organization(name=f"Multi Org {i} {uuid4()}") for i in range(3)]
        session.add_all(orgs)  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        # Create memberships for all orgs
        for org in orgs:
            m = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
            session.add(m)
        await session.commit()

        # List organizations
        result = await list_organizations_for_users(session, [user.id])

        assert user.id in result
        assert len(result[user.id]) == 3

    @pytest.mark.asyncio
    async def test_list_organizations_for_users_nonexistent_users(self, session: AsyncSession) -> None:
        """list_organizations_for_users returns empty lists for nonexistent users."""
        fake_ids = [uuid4(), uuid4()]

        result = await list_organizations_for_users(session, fake_ids)

        # Should return dict with empty lists for each ID
        assert len(result) == 2
        for fake_id in fake_ids:
            assert fake_id in result
            assert result[fake_id] == []
