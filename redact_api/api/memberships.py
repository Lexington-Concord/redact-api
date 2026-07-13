"""Membership CRUD endpoints for user-organization relationships."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from redact_api.core.activity_logging import ActivityAction, log_activity_decorator
from redact_api.core.pagination import ParamsDep
from redact_api.core.permissions import RequireAdmin, RequireOwner
from redact_api.core.tenants import TenantDep
from redact_api.db.session import SessionDep
from redact_api.models.membership import (
    Membership,
    MembershipCreate,
    MembershipRead,
    MembershipUpdate,
)
from redact_api.services.membership_service import (
    create_membership,
    delete_membership,
    get_membership,
    update_membership,
)
from redact_api.services.organization_service import get_organization
from redact_api.services.user_service import get_user

router = APIRouter(prefix="/memberships", tags=["memberships"])


@router.post("", response_model=MembershipRead, status_code=status.HTTP_201_CREATED)
@log_activity_decorator(ActivityAction.CREATE, "membership")
async def create_membership_endpoint(
    payload: MembershipCreate,
    session: SessionDep,
    role_check: RequireAdmin,  # noqa: ARG001
) -> MembershipRead:
    """Add a member to the organization.

    Requires ADMIN role or higher (OWNER).
    """
    user = await get_user(session, payload.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User does not exist",
        )
    organization = await get_organization(session, payload.organization_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization does not exist",
        )
    try:
        membership = await create_membership(session, payload)
        await session.commit()
    except IntegrityError as e:
        if "uq_membership_user_org" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already a member of this organization",
            ) from None
        raise
    return MembershipRead.model_validate(membership)


@router.get("", response_model=Page[MembershipRead])
async def list_memberships_endpoint(
    session: SessionDep,
    params: ParamsDep,
) -> Page[MembershipRead]:
    return await apaginate(session, select(Membership).order_by(Membership.created_at), params)


@router.patch("/{membership_id}", response_model=MembershipRead)
@log_activity_decorator(ActivityAction.UPDATE, "membership")
async def update_membership_endpoint(
    membership_id: UUID,
    payload: MembershipUpdate,
    session: SessionDep,
    tenant: TenantDep,
    role_check: RequireOwner,  # noqa: ARG001
) -> MembershipRead:
    """Update membership role.

    Requires OWNER role. Only role changes are supported.
    Users cannot escalate their own role.
    """
    membership = await get_membership(session, membership_id)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership not found",
        )

    # Prevent self-role changes
    if membership.user_id == tenant.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot change your own role",
        )

    updated = await update_membership(session, membership, payload)
    await session.commit()
    return MembershipRead.model_validate(updated)


@router.delete("/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
@log_activity_decorator(ActivityAction.DELETE, "membership", resource_id_param_name="membership_id")
async def delete_membership_endpoint(
    membership_id: UUID,
    session: SessionDep,
    role_check: RequireAdmin,  # noqa: ARG001
) -> None:
    """Remove a member from the organization.

    Requires ADMIN role or higher (OWNER).
    """
    membership = await get_membership(session, membership_id)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership not found",
        )
    rows_deleted = await delete_membership(session, membership)
    await session.commit()

    # Handle race condition: if another request deleted the membership first
    if rows_deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership not found",
        )
