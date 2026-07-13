"""Organization data access helpers for services and endpoints.

Security Note:
    Organization operations are inherently tenant-isolated since organizations
    ARE the tenant boundary. However, operations must still verify that:
    - get_organization: User has membership in requested org
    - list_organizations: Only returns orgs the user is a member of
    - update_organization: User has membership in org being updated
    - delete_organization: User has membership (and appropriate role) in org
"""

import logging
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from redact_api.core.config import settings
from redact_api.core.logging import get_logging_context
from redact_api.core.metrics import (
    active_memberships_gauge,
    database_query_duration_seconds,
    organizations_created_total,
)
from redact_api.models.membership import Membership
from redact_api.models.organization import (
    Organization,
    OrganizationCreate,
    OrganizationUpdate,
)
from redact_api.models.user import User

LOGGER = logging.getLogger(__name__)


async def get_organization(
    session: AsyncSession, organization_id: UUID, user_id: UUID | None = None
) -> Organization | None:
    """Fetch a single organization by ID.

    Records database query duration metric.

    Args:
        session: Database session
        organization_id: UUID of organization to retrieve
        user_id: Optional user ID to verify membership
                (recommended for tenant isolation)

    Returns:
        Organization if found (and user has access if user_id provided),
        None otherwise

    Security Note:
        When user_id is provided, this verifies the user is a member of the
        organization. This prevents users from accessing organizations they
        don't belong to.
    """
    start = time.perf_counter()
    stmt = select(Organization).where(col(Organization.id) == organization_id)

    # If user_id provided, verify membership for tenant isolation
    if user_id:
        stmt = stmt.join(Membership, col(Membership.organization_id) == col(Organization.id))
        stmt = stmt.where(col(Membership.user_id) == user_id)

    result = await session.execute(stmt)
    duration = time.perf_counter() - start
    database_query_duration_seconds.labels(query_type="select").observe(duration)
    return result.scalar_one_or_none()


async def list_organizations(
    session: AsyncSession,
    offset: int = 0,
    limit: int = 100,
    user_id: UUID | None = None,
) -> list[Organization]:
    """List organizations with pagination.

    Records database query duration metric.

    Args:
        session: Database session
        offset: Pagination offset
        limit: Maximum number of results
        user_id: Optional user ID to filter to only organizations user
                is member of

    Returns:
        List of organizations (filtered by user membership if user_id
        provided)

    Security Note:
        When user_id is provided, only returns organizations the user is a
        member of. This is critical for tenant isolation - users should only
        see their own orgs.
    """
    start = time.perf_counter()
    stmt = select(Organization)

    # Filter by user membership for tenant isolation
    if user_id:
        stmt = stmt.join(Membership, col(Membership.organization_id) == col(Organization.id))
        stmt = stmt.where(col(Membership.user_id) == user_id)

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    duration = time.perf_counter() - start
    database_query_duration_seconds.labels(query_type="select").observe(duration)
    return list(result.scalars().all())


async def create_organization(session: AsyncSession, payload: OrganizationCreate) -> Organization:
    """Create a new organization.

    Increments the organizations_created_total counter metric after successful creation.

    Example of structured logging pattern:
        - Log operation start with input metadata
        - Log operation success with result metadata
        - Include request context (user_id, org_id, request_id) automatically
    """
    context = get_logging_context()

    # Log operation start
    LOGGER.info(
        "creating_organization",
        extra={
            **context,
            "organization_name": payload.name,
        },
    )

    organization = Organization(**payload.model_dump())
    session.add(organization)
    await session.flush()  # type: ignore[attr-defined]
    await session.refresh(organization)

    # Increment counter after successful creation
    organizations_created_total.labels(environment=settings.environment).inc()

    # Log operation success
    LOGGER.info(
        "organization_created",
        extra={
            **context,
            "organization_id": str(organization.id),
            "organization_name": organization.name,
        },
    )

    return organization


async def update_organization(
    session: AsyncSession, organization: Organization, payload: OrganizationUpdate
) -> Organization:
    """Update organization settings.

    Security Note:
        Caller MUST verify user has permission to update this organization.
        Required role: ADMIN or OWNER
    """
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(organization, field, value)
    session.add(organization)
    await session.flush()  # type: ignore[attr-defined]
    await session.refresh(organization)
    return organization


async def delete_organization(session: AsyncSession, organization: Organization) -> None:
    """Delete an organization.

    Decrements active_memberships_gauge by the count of memberships
    associated with this organization before deletion.

    Security Note:
        Caller MUST verify user has permission to delete this organization.
        Required role: OWNER

        This is a destructive operation. Deletion will CASCADE to:
        - Memberships (users lose access)
        - Documents (all org data deleted)
        - Any other org-scoped resources
    """
    # Count memberships for this organization before deletion
    membership_count_result = await session.execute(
        select(Membership).where(col(Membership.organization_id) == organization.id)
    )
    membership_count = len(list(membership_count_result.scalars().all()))

    await session.delete(organization)
    await session.flush()  # type: ignore[attr-defined]

    # Decrement gauge by the number of memberships that were deleted
    if membership_count > 0:
        active_memberships_gauge.labels(environment=settings.environment).dec(membership_count)


async def list_users_for_organization(session: AsyncSession, organization_id: UUID) -> list[User]:
    result = await session.execute(
        select(User)
        .join(Membership, col(Membership.user_id) == col(User.id))
        .where(col(Membership.organization_id) == organization_id)
    )
    return list(result.scalars().all())


async def list_users_for_organizations(session: AsyncSession, organization_ids: list[UUID]) -> dict[UUID, list[User]]:
    if not organization_ids:
        return {}
    result = await session.execute(
        select(Membership.organization_id, User)
        .join(User, col(Membership.user_id) == col(User.id))
        .where(col(Membership.organization_id).in_(organization_ids))
    )
    mapping: dict[UUID, list[User]] = {org_id: [] for org_id in organization_ids}
    for organization_id, user in result.all():
        if organization_id in mapping:
            mapping[organization_id].append(user)
    return mapping
