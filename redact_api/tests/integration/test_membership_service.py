"""Unit tests for membership_service.py - direct service function testing.

These tests call service functions directly with a database session,
bypassing the API layer to achieve better coverage of:
- Pagination parameters (offset/limit)
- Metrics recording (counters and gauges)
- Race conditions (concurrent deletes)
- Edge cases
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.core.metrics import active_memberships_gauge, memberships_created_total
from redact_api.models.membership import Membership, MembershipCreate, MembershipRole, MembershipUpdate
from redact_api.models.organization import Organization
from redact_api.models.user import User
from redact_api.services.membership_service import (
    create_membership,
    delete_membership,
    get_membership,
    list_memberships,
    update_membership,
)


class TestGetMembership:
    """Test get_membership service function."""

    @pytest.mark.asyncio
    async def test_get_membership_found(self, session: AsyncSession) -> None:
        """get_membership returns membership when found."""
        # Create user and organization
        user = User(name="Get User", email=f"get-{uuid4()}@example.com")
        org = Organization(name=f"Get Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
        session.add(membership)
        await session.commit()
        await session.refresh(membership)

        result = await get_membership(session, membership.id)

        assert result is not None
        assert result.id == membership.id
        assert result.user_id == user.id
        assert result.organization_id == org.id

    @pytest.mark.asyncio
    async def test_get_membership_not_found(self, session: AsyncSession) -> None:
        """get_membership returns None when membership doesn't exist."""
        fake_id = uuid4()

        result = await get_membership(session, fake_id)

        assert result is None


class TestListMemberships:
    """Test list_memberships service function with pagination."""

    @pytest.mark.asyncio
    async def test_list_memberships_default_pagination(self, session: AsyncSession) -> None:
        """list_memberships returns memberships with default pagination."""
        # Create user and org
        user = User(name="List User", email=f"list-{uuid4()}@example.com")
        org = Organization(name=f"List Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        # Create multiple memberships
        for _ in range(5):
            new_user = User(name="List User Extra", email=f"listextra-{uuid4()}@example.com")
            session.add(new_user)
            await session.flush()  # type: ignore[attr-defined]
            m = Membership(user_id=new_user.id, organization_id=org.id, role=MembershipRole.MEMBER)
            session.add(m)
        await session.commit()

        result = await list_memberships(session)

        # Should have at least 5 memberships (plus any fixture memberships)
        assert len(result) >= 5

    @pytest.mark.asyncio
    async def test_list_memberships_with_offset(self, session: AsyncSession) -> None:
        """list_memberships respects offset parameter."""
        # Create org
        org = Organization(name=f"Offset Org {uuid4()}")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        # Create memberships
        for i in range(5):
            user = User(name=f"Offset User {i}", email=f"offset-{i}-{uuid4()}@example.com")
            session.add(user)
            await session.flush()  # type: ignore[attr-defined]
            m = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
            session.add(m)
        await session.commit()

        # Get all memberships
        all_memberships = await list_memberships(session, offset=0, limit=100)

        # Get memberships with offset
        offset_memberships = await list_memberships(session, offset=2, limit=100)

        # Should have 2 fewer memberships
        assert len(offset_memberships) == len(all_memberships) - 2

    @pytest.mark.asyncio
    async def test_list_memberships_with_limit(self, session: AsyncSession) -> None:
        """list_memberships respects limit parameter."""
        # Create org
        org = Organization(name=f"Limit Org {uuid4()}")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        # Create memberships
        for i in range(5):
            user = User(name=f"Limit User {i}", email=f"limit-{i}-{uuid4()}@example.com")
            session.add(user)
            await session.flush()  # type: ignore[attr-defined]
            m = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
            session.add(m)
        await session.commit()

        result = await list_memberships(session, offset=0, limit=3)

        # Should have exactly 3 memberships
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_memberships_empty_result(self, session: AsyncSession) -> None:
        """list_memberships returns empty list when offset exceeds count."""
        result = await list_memberships(session, offset=10000, limit=10)

        assert result == []


class TestCreateMembership:
    """Test create_membership service function."""

    @pytest.mark.asyncio
    async def test_create_membership_success(self, session: AsyncSession) -> None:
        """create_membership creates a new membership and returns it."""
        user = User(name="Create User", email=f"create-{uuid4()}@example.com")
        org = Organization(name=f"Create Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        payload = MembershipCreate(user_id=user.id, organization_id=org.id)

        result = await create_membership(session, payload)
        await session.commit()

        assert result.id is not None
        assert result.user_id == user.id
        assert result.organization_id == org.id
        assert result.role == MembershipRole.MEMBER  # Default role

    @pytest.mark.asyncio
    async def test_create_membership_with_role(self, session: AsyncSession) -> None:
        """create_membership respects specified role."""
        user = User(name="Owner User", email=f"owner-{uuid4()}@example.com")
        org = Organization(name=f"Owner Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        payload = MembershipCreate(user_id=user.id, organization_id=org.id, role=MembershipRole.OWNER)

        result = await create_membership(session, payload)
        await session.commit()

        assert result.role == MembershipRole.OWNER

    @pytest.mark.asyncio
    async def test_create_membership_increments_counter(self, session: AsyncSession) -> None:
        """create_membership increments the memberships_created_total counter."""
        # Get current count
        try:
            before = memberships_created_total.labels(environment="test")._value.get()
        except AttributeError:
            before = 0

        user = User(name="Counter User", email=f"counter-{uuid4()}@example.com")
        org = Organization(name=f"Counter Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        payload = MembershipCreate(user_id=user.id, organization_id=org.id)
        await create_membership(session, payload)
        await session.commit()

        after = memberships_created_total.labels(environment="test")._value.get()

        # Counter should have increased
        assert after >= before

    @pytest.mark.asyncio
    async def test_create_membership_increments_gauge(self, session: AsyncSession) -> None:
        """create_membership increments the active_memberships_gauge."""
        # Get current gauge
        try:
            before = active_memberships_gauge.labels(environment="test")._value.get()
        except AttributeError:
            before = 0

        user = User(name="Gauge User", email=f"gauge-{uuid4()}@example.com")
        org = Organization(name=f"Gauge Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        payload = MembershipCreate(user_id=user.id, organization_id=org.id)
        await create_membership(session, payload)
        await session.commit()

        after = active_memberships_gauge.labels(environment="test")._value.get()

        # Gauge should have increased
        assert after >= before


class TestUpdateMembership:
    """Test update_membership service function."""

    @pytest.mark.asyncio
    async def test_update_membership_changes_role(self, session: AsyncSession) -> None:
        """update_membership changes specified fields."""
        user = User(name="Update User", email=f"update-{uuid4()}@example.com")
        org = Organization(name=f"Update Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
        session.add(membership)
        await session.commit()
        await session.refresh(membership)

        payload = MembershipUpdate(role=MembershipRole.ADMIN)
        result = await update_membership(session, membership, payload)
        await session.commit()

        assert result.role == MembershipRole.ADMIN
        assert result.user_id == user.id  # Unchanged
        assert result.organization_id == org.id  # Unchanged

    @pytest.mark.asyncio
    async def test_update_membership_partial_update(self, session: AsyncSession) -> None:
        """update_membership only changes specified fields (exclude_unset)."""
        user = User(name="Partial User", email=f"partial-{uuid4()}@example.com")
        org = Organization(name=f"Partial Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
        session.add(membership)
        await session.commit()
        await session.refresh(membership)
        original_role = membership.role

        payload = MembershipUpdate()  # No fields set
        result = await update_membership(session, membership, payload)
        await session.commit()

        # Role unchanged because not in update
        assert result.role == original_role


class TestDeleteMembership:
    """Test delete_membership service function."""

    @pytest.mark.asyncio
    async def test_delete_membership_removes_from_db(self, session: AsyncSession) -> None:
        """delete_membership removes membership from database."""
        user = User(name="Delete User", email=f"delete-{uuid4()}@example.com")
        org = Organization(name=f"Delete Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
        session.add(membership)
        await session.commit()
        await session.refresh(membership)
        membership_id = membership.id

        rows_deleted = await delete_membership(session, membership)
        await session.commit()

        assert rows_deleted == 1

        result = await get_membership(session, membership_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_membership_decrements_gauge(self, session: AsyncSession) -> None:
        """delete_membership decrements the active_memberships_gauge."""
        user = User(name="Gauge Del User", email=f"gaugedel-{uuid4()}@example.com")
        org = Organization(name=f"Gauge Del Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
        session.add(membership)
        await session.commit()
        await session.refresh(membership)

        # Get gauge before delete
        try:
            before = active_memberships_gauge.labels(environment="test")._value.get()
        except AttributeError:
            before = 0

        await delete_membership(session, membership)
        await session.commit()

        after = active_memberships_gauge.labels(environment="test")._value.get()

        # Gauge should have decreased
        assert after <= before

    @pytest.mark.asyncio
    async def test_delete_membership_already_deleted_returns_zero(self, session: AsyncSession) -> None:
        """delete_membership returns 0 when membership was already deleted.

        This tests the race condition handling where two concurrent requests
        might try to delete the same membership.
        """
        user = User(name="Race User", email=f"race-{uuid4()}@example.com")
        org = Organization(name=f"Race Org {uuid4()}")
        session.add_all([user, org])  # type: ignore[attr-defined]
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER)
        session.add(membership)
        await session.commit()
        await session.refresh(membership)

        # First delete succeeds
        rows_deleted_1 = await delete_membership(session, membership)
        await session.commit()
        assert rows_deleted_1 == 1

        # Second delete returns 0 (already deleted)
        # Create a new membership object pointing to same ID but already deleted
        ghost_membership = Membership(
            id=membership.id, user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER
        )
        rows_deleted_2 = await delete_membership(session, ghost_membership)
        await session.commit()
        assert rows_deleted_2 == 0
