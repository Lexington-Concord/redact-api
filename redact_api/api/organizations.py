"""Organization CRUD endpoints and membership expansion."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi_pagination import Page, create_page
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy import select

from redact_api.core.activity_logging import ActivityAction, log_activity_decorator
from redact_api.core.pagination import ParamsDep
from redact_api.core.permissions import RequireAdmin, RequireOwner
from redact_api.core.tenants import TenantDep
from redact_api.db.session import SessionDep
from redact_api.models.membership import Membership, MembershipRole
from redact_api.models.organization import (
    Organization,
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)
from redact_api.models.shared import UserInfo
from redact_api.services.organization_service import (
    create_organization,
    delete_organization,
    get_organization,
    list_users_for_organization,
    list_users_for_organizations,
    update_organization,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
@log_activity_decorator(ActivityAction.CREATE, "organization")
async def create_org(
    payload: OrganizationCreate,
    session: SessionDep,
    tenant: TenantDep,
) -> OrganizationRead:
    organization = await create_organization(session, payload)

    # Create OWNER membership for the creating user
    membership = Membership(
        user_id=tenant.user_id,
        organization_id=organization.id,
        role=MembershipRole.OWNER,
    )
    session.add(membership)

    await session.commit()

    # Return actual users (including the auto-created OWNER membership)
    users = await list_users_for_organization(session, organization.id)
    response = OrganizationRead.model_validate(organization)
    response.users = [UserInfo.model_validate(user) for user in users]
    return response


@router.get("", response_model=Page[OrganizationRead])
async def list_orgs(
    session: SessionDep,
    params: ParamsDep,
) -> Page[OrganizationRead]:
    page = await apaginate(session, select(Organization).order_by(Organization.created_at), params)
    organizations = page.items
    organization_ids = [org.id for org in organizations]
    users_by_org = await list_users_for_organizations(session, organization_ids)
    items: list[OrganizationRead] = []
    for organization in organizations:
        response = OrganizationRead.model_validate(organization)
        response.users = [UserInfo.model_validate(user) for user in users_by_org.get(organization.id, [])]
        items.append(response)
    return create_page(items, total=page.total, params=params)  # type: ignore[return-value]


@router.get("/{organization_id}", response_model=OrganizationRead)
@log_activity_decorator(ActivityAction.READ, "organization")
async def get_org(
    organization_id: UUID,
    session: SessionDep,
    tenant: TenantDep,
) -> OrganizationRead:
    organization = await get_organization(session, organization_id, user_id=tenant.user_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    users = await list_users_for_organization(session, organization_id)
    response = OrganizationRead.model_validate(organization)
    response.users = [UserInfo.model_validate(user) for user in users]
    return response


@router.patch("/{organization_id}", response_model=OrganizationRead)
@log_activity_decorator(ActivityAction.UPDATE, "organization")
async def update_org(
    organization_id: UUID,
    payload: OrganizationUpdate,
    session: SessionDep,
    tenant: TenantDep,
    role_check: RequireAdmin,  # noqa: ARG001
) -> OrganizationRead:
    """Update organization settings.

    Requires ADMIN role or higher (OWNER).
    """
    organization = await get_organization(session, organization_id, user_id=tenant.user_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    updated = await update_organization(session, organization, payload)
    await session.commit()
    users = await list_users_for_organization(session, organization_id)
    response = OrganizationRead.model_validate(updated)
    response.users = [UserInfo.model_validate(user) for user in users]
    return response


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
@log_activity_decorator(ActivityAction.DELETE, "organization", resource_id_param_name="organization_id")
async def delete_org(
    organization_id: UUID,
    session: SessionDep,
    tenant: TenantDep,
    role_check: RequireOwner,  # noqa: ARG001
) -> None:
    """Delete organization and all associated data.

    Requires OWNER role. This is a destructive operation that cascades to:
    - All memberships (users lose access)
    - All documents and resources
    - Cannot be undone
    """
    organization = await get_organization(session, organization_id, user_id=tenant.user_id)
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    await delete_organization(session, organization)
    await session.commit()
