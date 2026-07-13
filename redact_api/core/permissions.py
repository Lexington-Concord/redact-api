"""Role-Based Access Control (RBAC) dependencies for organization permissions.

This module provides FastAPI dependencies to enforce role-based permissions within
organizations. It builds on top of tenant isolation to add fine-grained access control.

Key Security Principles:
- ROLE HIERARCHY: OWNER > ADMIN > MEMBER
- EXPLICIT PERMISSIONS: Dangerous operations require explicit role checks
- FAIL CLOSED: Missing or insufficient role returns 403

Exports:
    require_role: Factory function for role-checking dependencies
    RequireOwner: Type alias for OWNER role requirement
    RequireAdmin: Type alias for ADMIN role requirement
    RequireMember: Type alias for MEMBER role requirement

Usage:

    from redact_api.core.permissions import RequireAdmin, RequireOwner
    from redact_api.core.tenants import TenantDep

    # Require ADMIN role to add members
    @router.post("/memberships")
    async def add_member(
        session: SessionDep,
        tenant: TenantDep,
        role_check: RequireAdmin,
        payload: MembershipCreate,
    ) -> MembershipRead:
        # role_check ensures user has ADMIN or OWNER role
        ...

    # Require OWNER role to delete organization
    @router.delete("/organizations/{organization_id}")
    async def delete_org(
        organization_id: UUID,
        session: SessionDep,
        tenant: TenantDep,
        role_check: RequireOwner,
    ) -> None:
        # role_check ensures user has OWNER role
        ...
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.core.tenants import TenantContext
from redact_api.db.session import SessionDep
from redact_api.models.membership import Membership, MembershipRole

__all__ = [
    "RequireAdmin",
    "RequireMember",
    "RequireOwner",
    "require_role",
]

LOGGER = logging.getLogger(__name__)


async def _get_user_role(
    session: AsyncSession,
    user_id: UUID,
    organization_id: UUID,
) -> MembershipRole | None:
    """Get user's role in the specified organization.

    DEPRECATED: This function is kept for backwards compatibility but should not be used.
    Use tenant.role from TenantContext instead, which is cached from the tenant validation
    query to avoid redundant database queries.

    Args:
        session: Database session
        user_id: UUID of user to check
        organization_id: UUID of organization

    Returns:
        MembershipRole if user is a member, None otherwise

    Security Note:
        This is a critical security function. It determines what actions
        a user can perform within an organization.
    """
    result = await session.execute(
        select(Membership.role)
        .where(Membership.user_id == user_id)
        .where(Membership.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


def _role_hierarchy_check(user_role: MembershipRole, required_role: MembershipRole) -> bool:
    """Check if user's role satisfies the required role.

    Role hierarchy: OWNER > ADMIN > MEMBER

    Args:
        user_role: User's actual role
        required_role: Minimum required role

    Returns:
        True if user_role >= required_role in hierarchy

    Examples:
        OWNER satisfies ADMIN requirement: True
        OWNER satisfies MEMBER requirement: True
        ADMIN satisfies OWNER requirement: False
        MEMBER satisfies ADMIN requirement: False
    """
    hierarchy = {
        MembershipRole.OWNER: 3,
        MembershipRole.ADMIN: 2,
        MembershipRole.MEMBER: 1,
    }
    return hierarchy.get(user_role, 0) >= hierarchy.get(required_role, 0)


def require_role(required_role: MembershipRole) -> object:
    """Dependency factory for role-based access control.

    Creates a FastAPI dependency that validates the user has the required
    role (or higher) in the current organization.

    Args:
        required_role: Minimum role required to access the endpoint

    Returns:
        FastAPI dependency function

    Raises:
        HTTPException: 403 if user lacks required role

    Example:
        RequireAdmin = Annotated[None, Depends(require_role(MembershipRole.ADMIN))]

        @router.post("/members")
        async def add_member(role_check: RequireAdmin) -> None:
            # User has ADMIN or OWNER role
            ...
    """

    async def _check_role(
        request: Request,
        session: SessionDep,
    ) -> None:
        """Check if user has required role in organization.

        Optimization: Uses the cached role from TenantContext instead of querying
        the database again. The role was already fetched during tenant validation.

        Args:
            request: FastAPI Request (contains tenant context)
            session: Database session (unused, kept for backwards compatibility)

        Raises:
            HTTPException: 403 if insufficient role
            HTTPException: 401 if tenant context missing
        """
        # session parameter kept for backwards compatibility but not used
        _ = session

        # Get tenant context from request state (set by TenantIsolationMiddleware)
        tenant: TenantContext | None = getattr(request.state, "tenant", None)
        if not tenant:
            LOGGER.error(
                "Tenant context not set - TenantIsolationMiddleware may be misconfigured",
                extra={"endpoint": request.url.path, "method": request.method},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error",
            )

        # Use cached role from tenant context (fetched during tenant validation)
        user_role = tenant.role

        # Check role hierarchy
        if not _role_hierarchy_check(user_role, required_role):
            LOGGER.warning(
                "Permission denied for role check",
                extra={
                    "user_id": str(tenant.user_id),
                    "organization_id": str(tenant.organization_id),
                    "user_role": user_role.value,
                    "required_role": required_role.value,
                    "endpoint": request.url.path,
                    "method": request.method,
                    "client_ip": request.client.host if request.client else None,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )

        LOGGER.debug(
            "Role check passed",
            extra={
                "user_id": str(tenant.user_id),
                "organization_id": str(tenant.organization_id),
                "user_role": user_role.value,
                "required_role": required_role.value,
            },
        )

    return _check_role


# Type aliases for common role requirements
RequireOwner = Annotated[None, Depends(require_role(MembershipRole.OWNER))]
RequireAdmin = Annotated[None, Depends(require_role(MembershipRole.ADMIN))]
RequireMember = Annotated[None, Depends(require_role(MembershipRole.MEMBER))]
