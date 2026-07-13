"""Membership data access helpers for services and endpoints."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from redact_api.core.config import settings
from redact_api.core.metrics import (
    active_memberships_gauge,
    memberships_created_total,
)
from redact_api.models.membership import (
    Membership,
    MembershipCreate,
    MembershipUpdate,
)


async def get_membership(session: AsyncSession, membership_id: UUID) -> Membership | None:
    result = await session.execute(select(Membership).where(col(Membership.id) == membership_id))
    return result.scalar_one_or_none()


async def list_memberships(session: AsyncSession, offset: int = 0, limit: int = 100) -> list[Membership]:
    result = await session.execute(select(Membership).offset(offset).limit(limit))
    return list(result.scalars().all())


async def create_membership(session: AsyncSession, payload: MembershipCreate) -> Membership:
    """Create a new membership.

    Increments memberships_created_total counter and updates active_memberships_gauge
    after successful creation.
    """
    membership = Membership(**payload.model_dump())
    session.add(membership)
    await session.flush()  # type: ignore[attr-defined]
    await session.refresh(membership)

    # Record metrics after successful creation
    memberships_created_total.labels(environment=settings.environment).inc()
    active_memberships_gauge.labels(environment=settings.environment).inc()

    return membership


async def update_membership(session: AsyncSession, membership: Membership, payload: MembershipUpdate) -> Membership:
    """Update membership (primarily for role changes).

    Security Note:
        Caller MUST verify user has permission to update this membership.
        Typically this means:
        - User has OWNER role in the organization
        - User cannot escalate their own role (should be enforced at endpoint)
    """
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(membership, field, value)
    session.add(membership)
    await session.flush()  # type: ignore[attr-defined]
    await session.refresh(membership)
    return membership


async def is_user_member(session: AsyncSession, user_id: UUID, organization_id: UUID) -> bool:
    """Check if user is a member of the specified organization.

    Args:
        session: Database session
        user_id: User UUID to check
        organization_id: Organization UUID to check

    Returns:
        True if user is a member of the organization, False otherwise
    """
    result = await session.execute(
        select(Membership).where(
            col(Membership.user_id) == user_id, col(Membership.organization_id) == organization_id
        )
    )
    return result.scalar_one_or_none() is not None


async def delete_membership(session: AsyncSession, membership: Membership) -> int:
    """Delete a membership.

    Decrements active_memberships_gauge after successful deletion.

    Returns the number of rows deleted (0 if already deleted by concurrent request, 1 if deleted).

    Security Note:
        Caller MUST verify user has permission to delete this membership.
        Typically this means:
        - User has ADMIN or OWNER role in the organization
    """
    # Use explicit DELETE statement to get rowcount for race condition handling
    result = await session.execute(delete(Membership).where(col(Membership.id) == membership.id))
    await session.flush()  # type: ignore[attr-defined]

    # Only decrement gauge if we actually deleted a row
    if result.rowcount and result.rowcount > 0:
        active_memberships_gauge.labels(environment=settings.environment).dec()

    return result.rowcount or 0
