"""Tenant isolation middleware and dependencies for multi-tenant applications.

This module provides critical security controls to prevent cross-tenant data access
in multi-tenant SaaS applications. It enforces tenant isolation at the middleware
level and provides utilities for service-layer query filtering.

Key Security Principles:
- DENY BY DEFAULT: All endpoints must explicitly opt into tenant context
- FAIL CLOSED: Missing tenant context returns 401/403, never serves data
- DEFENSE IN DEPTH: Multiple layers (middleware, dependencies, query filters)
- EXPLICIT PUBLIC: Public endpoints must be explicitly listed

Usage:

    # In main.py - Add middleware (AFTER AuthMiddleware)
    from redact_api.core.tenants import TenantIsolationMiddleware
    app.add_middleware(TenantIsolationMiddleware)

    # In endpoints - Require tenant isolation
    from redact_api.core.tenants import TenantDep

    @router.get("/documents")
    async def list_documents(
        session: SessionDep,
        tenant: TenantDep,
    ) -> list[DocumentRead]:
        # All queries automatically scoped to tenant.organization_id
        stmt = select(Document).where(
            Document.organization_id == tenant.organization_id
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # In services - Add tenant filters to queries
    from redact_api.core.tenants import add_tenant_filter

    async def get_documents(
        session: AsyncSession, tenant: TenantContext
    ) -> list[Document]:
        stmt = select(Document)
        stmt = add_tenant_filter(stmt, tenant, Document.organization_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from redact_api.core.auth import CurrentUser
from redact_api.core.config import settings
from redact_api.models.membership import Membership, MembershipRole

LOGGER = logging.getLogger(__name__)

# Public endpoints that don't require tenant isolation
# These paths are accessible without authentication or tenant context
PUBLIC_ENDPOINTS = [
    "/health",
    "/ping",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/metrics",
]


class TenantContext(BaseModel):
    """Tenant context for the current request.

    This model represents the active tenant (organization) for the current request.
    It's populated by TenantIsolationMiddleware and enforced via TenantDep.

    Security Implications:
    - All data access MUST be scoped to organization_id
    - User must be a member of the organization (verified by middleware)
    - Missing tenant context indicates authentication/authorization failure

    Attributes:
        organization_id: UUID of the current tenant/organization
        user_id: UUID of the authenticated user making the request
        role: User's role in the organization (cached from validation query)
    """

    organization_id: UUID = Field(..., description="Current tenant/organization identifier")
    user_id: UUID = Field(..., description="Authenticated user making the request")
    role: MembershipRole = Field(..., description="User's role in the organization")

    @property
    def is_isolated(self) -> bool:
        """Check if tenant isolation is properly configured.

        Returns:
            True if tenant has valid organization_id and user_id
        """
        return bool(self.organization_id and self.user_id)


async def _validate_user_org_access(
    session: AsyncSession,
    user_id: UUID,
    organization_id: UUID,
) -> tuple[bool, MembershipRole | None]:
    """Validate that user has access to the specified organization and return their role.

    This is a critical security check that prevents users from accessing
    organizations they don't belong to. Called by TenantIsolationMiddleware
    before granting tenant context.

    Optimization: This function performs a single database query to both validate
    membership AND retrieve the user's role, eliminating the need for a separate
    role query later in the RBAC layer.

    Args:
        session: Database session for membership query
        user_id: UUID of user to validate
        organization_id: UUID of organization to check access for

    Returns:
        Tuple of (has_access, role):
        - has_access: True if user is a member, False otherwise
        - role: User's MembershipRole if member, None otherwise

    Security Note:
        This function MUST be called before setting tenant context.
        Failure to validate membership allows cross-tenant access.
    """
    result = await session.execute(
        select(Membership.role).where(
            Membership.user_id == user_id,
            Membership.organization_id == organization_id,
        )
    )
    role = result.scalar_one_or_none()
    return (role is not None, role)


def _extract_org_id_from_jwt(current_user: object) -> UUID | None:
    """Extract organization_id from JWT claims.

    Args:
        current_user: Authenticated user object from AuthMiddleware

    Returns:
        UUID if found in JWT claims, None otherwise
    """
    if hasattr(current_user, "organization_id") and current_user.organization_id:
        organization_id = current_user.organization_id
        LOGGER.debug("Extracted tenant from JWT claims: %s", str(organization_id))
        return organization_id
    return None


def _extract_org_id_from_path(request: Request) -> tuple[UUID | None, Response | None]:
    """Extract organization_id from path parameters.

    Args:
        request: FastAPI Request object

    Returns:
        Tuple of (organization_id, error_response)
        If successful, returns (UUID, None)
        If error, returns (None, JSONResponse with 400)
    """
    if "org_id" not in request.path_params:
        return None, None

    try:
        org_id_str = request.path_params["org_id"]
        organization_id = UUID(org_id_str)
        LOGGER.debug("Extracted tenant from path parameter: %s", str(organization_id))
    except (ValueError, TypeError) as err:
        invalid_org_msg = "Invalid organization ID format in path"
        LOGGER.warning("Invalid org_id in path: %s", str(err))
        error_response = JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": invalid_org_msg},
        )
        return None, error_response
    else:
        return organization_id, None


def _extract_org_id_from_query(request: Request) -> tuple[UUID | None, Response | None]:
    """Extract organization_id from query parameters.

    Args:
        request: FastAPI Request object

    Returns:
        Tuple of (organization_id, error_response)
        If successful, returns (UUID, None)
        If error, returns (None, JSONResponse with 400)
    """
    org_id_query = request.query_params.get("org_id")
    if not org_id_query:
        return None, None

    try:
        organization_id = UUID(org_id_query)
        LOGGER.debug("Extracted tenant from query param: %s", str(organization_id))
    except (ValueError, TypeError) as err:
        invalid_org_msg = "Invalid organization ID format in query"
        LOGGER.warning("Invalid org_id in query: %s", str(err))
        error_response = JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": invalid_org_msg},
        )
        return None, error_response
    else:
        return organization_id, None


async def _validate_tenant_context(
    request: Request,
    current_user: CurrentUser,
    session: AsyncSession | None = None,
) -> tuple[TenantContext | None, Response | None]:
    """Validate and extract tenant context for request.

    Validates that the authenticated user has access to the requested organization.
    If session is not provided, creates a temporary session for validation.

    Args:
        request: FastAPI Request object
        current_user: Authenticated user from auth middleware
        session: Optional AsyncSession to reuse (avoids creating new connection).
            If None, creates a temporary session for validation. Useful when called
            from endpoints that already have a session to avoid extra connections.

    Returns:
        Tuple of (tenant_context, error_response):
        - On success: (TenantContext, None)
        - On failure: (None, JSONResponse with 401/403)
    """
    # Extract organization_id from multiple sources with priority order
    organization_id = _extract_org_id_from_jwt(current_user)

    if not organization_id:
        organization_id, error_response = _extract_org_id_from_path(request)
        if error_response:
            return None, error_response

    if not organization_id:
        organization_id, error_response = _extract_org_id_from_query(request)
        if error_response:
            return None, error_response

    # Fail closed if no organization_id found
    if not organization_id:
        no_org_msg = "Organization context required but not provided"
        LOGGER.warning("Tenant isolation check failed: no organization_id found")
        return None, JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": no_org_msg},
        )

    # Validate user has access to this organization and get their role
    # Reuse provided session if available, otherwise create temporary one
    if session is not None:
        # Session provided - use it directly without creating new connection
        has_access, user_role = await _validate_user_org_access(session, current_user.id, organization_id)
    else:
        # No session provided - create temporary one for validation using app.state
        async with request.app.state.async_session_maker() as temp_session:
            has_access, user_role = await _validate_user_org_access(temp_session, current_user.id, organization_id)

    if not has_access:
        access_denied_msg = "User does not have access to this organization"
        LOGGER.warning(
            "Tenant isolation check failed: user %s attempted access to org %s",
            str(current_user.id),
            str(organization_id),
        )
        return None, JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": access_denied_msg},
        )

    # user_role is guaranteed to be non-None here because has_access is True
    if user_role is None:
        error_msg = "Role must be present when has_access is True"
        raise RuntimeError(error_msg)

    tenant_context = TenantContext(
        organization_id=organization_id,
        user_id=current_user.id,
        role=user_role,
    )
    LOGGER.debug(
        "Tenant isolation validated",
        extra={
            "user_id": str(current_user.id),
            "organization_id": str(organization_id),
        },
    )
    return tenant_context, None


class TenantIsolationMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce tenant isolation for multi-tenant applications.

    This middleware extracts tenant context from requests and validates that
    users have access to the requested organization. It provides defense-in-depth
    security by enforcing tenant isolation at the middleware level.

    Tenant Extraction Priority:
    1. JWT claims (organization_id or org_id field) - Primary method
    2. Path parameters (e.g., /orgs/{org_id}/resources) - For org-scoped endpoints
    3. Query parameters (org_id=xxx) - Legacy/convenience method

    Security Guarantees:
    - Returns 403 if user doesn't belong to requested organization
    - Returns 401 if tenant extraction fails
    - Skips validation for public endpoints only
    - Stores tenant in request.state for downstream access

    Usage in main.py:
        from redact_api.core.tenants import TenantIsolationMiddleware
        from redact_api.core.auth import AuthMiddleware

        # CRITICAL: TenantIsolationMiddleware must come AFTER AuthMiddleware
        app.add_middleware(AuthMiddleware)
        app.add_middleware(TenantIsolationMiddleware)
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Process request and enforce tenant isolation.

        Args:
            request: FastAPI Request object
            call_next: Next middleware in chain

        Returns:
            Response from downstream middleware/endpoint

        Raises:
            Returns JSONResponse with 401/403 for tenant isolation failures
        """
        # Skip tenant isolation if enforcement is disabled
        if not settings.enforce_tenant_isolation:
            LOGGER.debug("Tenant isolation enforcement disabled by configuration")
            request.state.tenant = None
            return await call_next(request)

        # Public endpoints don't require tenant isolation
        if any(request.url.path.startswith(path) for path in PUBLIC_ENDPOINTS):
            request.state.tenant = None
            return await call_next(request)

        # Get authenticated user from AuthMiddleware
        current_user = getattr(request.state, "user", None)
        if not current_user:
            missing_auth_msg = "Authentication required for tenant-isolated endpoint"
            LOGGER.warning("Tenant isolation check failed: no authenticated user")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": missing_auth_msg},
            )

        tenant_context, error_response = await _validate_tenant_context(request, current_user)
        if error_response:
            return error_response

        # Set tenant context for downstream use
        request.state.tenant = tenant_context
        return await call_next(request)


def get_tenant_context(request: Request) -> TenantContext:
    """Dependency for endpoints that require tenant isolation.

    Extracts TenantContext from request.state (populated by TenantIsolationMiddleware).
    Raises 401 if tenant context is not available.

    This dependency enforces that:
    1. TenantIsolationMiddleware has run and validated access
    2. User belongs to the organization
    3. All data access will be scoped to tenant.organization_id

    Args:
        request: FastAPI Request object

    Returns:
        TenantContext instance with organization_id and user_id

    Raises:
        HTTPException: 401 if tenant context not available

    Example:
        from redact_api.core.tenants import TenantDep

        @router.get("/documents")
        async def list_documents(tenant: TenantDep) -> list[DocumentRead]:
            # tenant.organization_id is guaranteed to be valid
            # User has been verified as member of this organization
            ...
    """
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        missing_tenant_msg = "Tenant context required but not available"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=missing_tenant_msg,
        )
    return tenant


# Type alias for dependency injection
TenantDep = Annotated[TenantContext, Depends(get_tenant_context)]


def add_tenant_filter(
    statement: Select,
    tenant: TenantContext,
    organization_column: ColumnElement[UUID],
) -> Select:
    """Add tenant isolation filter to SQLAlchemy query.

    This helper ensures all queries are scoped to the current tenant's organization.
    Using this function prevents accidental data leaks by enforcing WHERE clauses.

    Security Note:
        ALWAYS use this helper in service layer queries that access tenant-scoped data.
        Forgetting to filter by organization_id is a CRITICAL security vulnerability.

    Args:
        statement: SQLAlchemy Select statement to filter
        tenant: Current tenant context with organization_id
        organization_column: The organization_id column to filter on

    Returns:
        Modified Select statement with tenant filter applied

    Example:
        from redact_api.core.tenants import add_tenant_filter

        async def list_documents(
            session: AsyncSession,
            tenant: TenantContext,
        ) -> list[Document]:
            stmt = select(Document)
            stmt = add_tenant_filter(stmt, tenant, Document.organization_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())
    """
    return statement.where(organization_column == tenant.organization_id)


async def validate_tenant_ownership(
    session: AsyncSession,
    tenant: TenantContext,
    organization_id: UUID,
) -> None:
    """Validate that a resource belongs to the current tenant.

    Use this helper when accepting organization_id as input (e.g., creating resources)
    to ensure users can't create resources in other organizations.

    Args:
        session: Database session (required for signature consistency)
        tenant: Current tenant context
        organization_id: Organization ID from request payload

    Raises:
        HTTPException: 403 if organization_id doesn't match tenant

    Example:
        @router.post("/documents")
        async def create_document(
            session: SessionDep,
            tenant: TenantDep,
            payload: DocumentCreate,
        ) -> DocumentRead:
            # Prevent user from creating documents in other orgs
            await validate_tenant_ownership(session, tenant, payload.organization_id)
            ...
    """
    # session parameter accepted for consistency but not used
    # Keep for potential future use (e.g., organization existence check)
    _ = session

    if organization_id != tenant.organization_id:
        ownership_violation_msg = "Cannot create resource for different organization"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ownership_violation_msg,
        )
