"""User data access helpers for services and endpoints.

Metrics Usage Examples:
    This module demonstrates comprehensive Prometheus metrics integration:

    - Counters: users_created_total tracks total user creations
    - Histograms: database_query_duration_seconds tracks query performance
    - Gauges: Could track active_users_count (not implemented here)

    Metrics are recorded AFTER successful operations to ensure accuracy.
    Labels are used consistently (environment from settings.environment).
"""

import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from redact_api.core.config import settings
from redact_api.core.metrics import (
    database_query_duration_seconds,
    users_created_total,
)
from redact_api.models.membership import Membership
from redact_api.models.organization import Organization
from redact_api.models.user import User, UserCreate, UserUpdate


async def get_user(session: AsyncSession, user_id: UUID) -> User | None:
    """Fetch a single user by ID.

    Demonstrates histogram metric usage for tracking database query duration.
    Uses time.perf_counter() for high-precision timing.

    Example metric output:
        database_query_duration_seconds{query_type="select"} 0.0023
    """
    # Record timing for database query using histogram
    start = time.perf_counter()
    result = await session.execute(select(User).where(col(User.id) == user_id))
    duration = time.perf_counter() - start

    # Observe duration in histogram with query_type label
    database_query_duration_seconds.labels(query_type="select").observe(duration)

    return result.scalar_one_or_none()


async def list_users(session: AsyncSession, offset: int = 0, limit: int = 100) -> list[User]:
    result = await session.execute(select(User).offset(offset).limit(limit))
    return list(result.scalars().all())


async def create_user(session: AsyncSession, payload: UserCreate) -> User:
    """Create a new user.

    Demonstrates counter metric usage for tracking user creation events.
    Counter is incremented AFTER successful commit to ensure accuracy.

    Example metric output:
        users_created_total{environment="production"} 1234
        users_created_total{environment="staging"} 56

    Note:
        Metrics are recorded after successful operations only. If commit fails,
        the counter is not incremented, maintaining accurate totals.
    """
    user = User(**payload.model_dump())
    session.add(user)
    await session.flush()  # type: ignore[attr-defined]
    await session.refresh(user)

    # Increment counter AFTER successful creation
    # Label with environment to track metrics per deployment environment
    users_created_total.labels(environment=settings.environment).inc()

    return user


async def update_user(session: AsyncSession, user: User, payload: UserUpdate) -> User:
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(user, field, value)
    session.add(user)
    await session.flush()  # type: ignore[attr-defined]
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.flush()  # type: ignore[attr-defined]


async def list_organizations_for_user(session: AsyncSession, user_id: UUID) -> list[Organization]:
    result = await session.execute(
        select(Organization)
        .join(
            Membership,
            col(Membership.organization_id) == col(Organization.id),
        )
        .where(col(Membership.user_id) == user_id)
    )
    return list(result.scalars().all())


async def list_organizations_for_users(session: AsyncSession, user_ids: list[UUID]) -> dict[UUID, list[Organization]]:
    if not user_ids:
        return {}
    result = await session.execute(
        select(Membership.user_id, Organization)
        .join(
            Membership,
            col(Membership.organization_id) == col(Organization.id),
        )
        .where(col(Membership.user_id).in_(user_ids))
    )
    mapping: dict[UUID, list[Organization]] = {user_id: [] for user_id in user_ids}
    for user_id, organization in result.all():
        if user_id in mapping:
            mapping[user_id].append(organization)
    return mapping
