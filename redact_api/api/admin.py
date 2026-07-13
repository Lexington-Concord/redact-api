"""Admin and internal API endpoints.

SECURITY WARNING: All endpoints in this module are internal-only and MUST be
blocked from external access via Traefik or Ory Oathkeeper rules.

These endpoints are called by internal services (Ory Oathkeeper, Kratos) and should
never be accessible from the public internet.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.db.session import get_session
from redact_api.models.membership import Membership, MembershipRole
from redact_api.models.organization import Organization
from redact_api.models.user import User
from redact_api.services.membership_service import is_user_member

# Internal endpoints (called by Ory Oathkeeper authorizer)
router = APIRouter(prefix="/_admin/internal", tags=["admin-internal"])

# Webhook endpoints (called by Ory Kratos)
webhooks_router = APIRouter(prefix="/_admin/webhooks/kratos", tags=["admin-webhooks"])


@router.get("/check-org-membership")
async def check_org_membership(
    x_user_id: Annotated[str, Header()],
    x_selected_org: Annotated[str, Header()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    """Validate organization membership for Ory Oathkeeper authorizer.

    SECURITY: This endpoint MUST be blocked from external access via Traefik.
    Only Ory Oathkeeper (internal cluster traffic) should reach this.

    Ory Oathkeeper calls this endpoint to validate org membership before issuing JWT.
    If this returns 403, Ory Oathkeeper will not generate a JWT and the request fails.

    Args:
        x_user_id: User UUID from X-User-ID header (Kratos identity ID)
        x_selected_org: Organization UUID from X-Selected-Org header
        session: Database session

    Returns:
        {"allowed": True} if user is a member of the organization

    Raises:
        HTTPException: 400 if UUIDs are invalid format
        HTTPException: 403 if user is not a member of organization
    """
    try:
        user_id = UUID(x_user_id)
        org_id = UUID(x_selected_org)
    except ValueError as err:
        error_msg = "Invalid UUID format in headers"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        ) from err

    # Check if user is a member of the organization
    is_member = await is_user_member(session, user_id, org_id)

    if not is_member:
        error_msg = f"User {user_id} is not a member of organization {org_id}"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_msg,
        )

    return {"allowed": True}


class KratosIdentityTraits(BaseModel):
    """Kratos identity traits schema."""

    email: EmailStr
    name: dict[str, str] | None = None


class KratosIdentity(BaseModel):
    """Kratos identity payload."""

    id: str  # UUID as string from Kratos
    traits: KratosIdentityTraits


class KratosRegistrationPayload(BaseModel):
    """Kratos registration webhook payload."""

    identity: KratosIdentity


@webhooks_router.post("/registration")
async def handle_registration(
    payload: KratosRegistrationPayload,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Handle Kratos registration webhook.

    SECURITY: This endpoint MUST be blocked from external access via Traefik.
    Only Ory Kratos (internal cluster traffic) should reach this.

    Called by Kratos after successful registration to create:
    1. app_user record with kratos_identity_id
    2. Default organization for new user
    3. Membership with OWNER role

    This endpoint is idempotent - duplicate calls will return existing user.

    Args:
        payload: Kratos registration payload with identity details
        session: Database session

    Returns:
        {"status": "created" or "already_exists", "user_id": UUID, "organization_id": UUID}

    Example payload from Kratos:
        {
          "identity": {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "traits": {
              "email": "user@example.com",
              "name": {"first": "John", "last": "Doe"}
            }
          }
        }
    """
    identity_id = UUID(payload.identity.id)
    email = payload.identity.traits.email

    # Extract name from traits (optional)
    name_parts = payload.identity.traits.name or {}
    first_name = name_parts.get("first", "")
    last_name = name_parts.get("last", "")
    full_name = f"{first_name} {last_name}".strip() or email.split("@")[0]

    # Check if user already exists (idempotency)
    result = await session.execute(select(User).where(User.kratos_identity_id == identity_id))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        # Get user's default organization
        membership_result = await session.execute(
            select(Membership)
            .where(Membership.user_id == existing_user.id)
            .where(Membership.role == MembershipRole.OWNER)
            .limit(1)
        )
        membership = membership_result.scalar_one_or_none()
        org_id = str(membership.organization_id) if membership else None

        return {
            "status": "already_exists",
            "user_id": str(existing_user.id),
            "organization_id": org_id or "",
        }

    # Create user
    user = User(
        email=email,
        name=full_name,
        kratos_identity_id=identity_id,
    )
    session.add(user)
    await session.flush()  # type: ignore[attr-defined]  # Get user.id

    # Create default organization
    org = Organization(name=f"{full_name}'s Organization")
    session.add(org)
    await session.flush()  # type: ignore[attr-defined]  # Get org.id

    # Create OWNER membership
    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.OWNER,
    )
    session.add(membership)

    await session.commit()

    return {
        "status": "created",
        "user_id": str(user.id),
        "organization_id": str(org.id),
    }
