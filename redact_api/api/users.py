"""User CRUD endpoints and membership expansion."""

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from fastapi_pagination import Page, create_page
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from redact_api.core.activity_logging import ActivityAction, log_activity_decorator
from redact_api.core.auth import CurrentUserFromHeaders
from redact_api.core.background_tasks import send_welcome_email_task
from redact_api.core.pagination import ParamsDep
from redact_api.db.session import SessionDep
from redact_api.models.shared import OrganizationInfo
from redact_api.models.user import User, UserCreate, UserRead, UserUpdate
from redact_api.services.user_service import (
    create_user,
    delete_user,
    get_user,
    list_organizations_for_user,
    list_organizations_for_users,
    update_user,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@log_activity_decorator(ActivityAction.CREATE, "user")
async def create_user_endpoint(
    payload: UserCreate,
    session: SessionDep,
    current_user: CurrentUserFromHeaders,  # noqa: ARG001
) -> UserRead:
    """Create a new user and send welcome email asynchronously.

    This endpoint demonstrates the background task pattern:
    1. Create user in database (blocking, part of request)
    2. Send welcome email in background (non-blocking, fire-and-forget)

    The API response is returned immediately without waiting for email delivery.
    Email failures are logged but do not affect user creation.

    Note: Organization membership will be added in Phase 4.
    """
    try:
        user = await create_user(session, payload)
        await session.commit()
    except IntegrityError as e:
        error_str = str(e).lower()
        if "uq_app_user_email" in error_str or "app_user_email_key" in error_str or "unique" in error_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists",
            ) from None
        raise

    # Send welcome email in background (non-blocking, fire-and-forget)
    # RUF006: Store task reference. Task lifecycle is managed by event loop;
    # variable prevents premature garbage collection in CPython.
    if user.id is not None:
        asyncio.create_task(send_welcome_email_task(user.id, user.email))  # noqa: RUF006

    # Load organizations for the newly created user (includes tenant's org)
    organizations = await list_organizations_for_user(session, user.id)
    response = UserRead.model_validate(user)
    response.organizations = [OrganizationInfo.model_validate(org) for org in organizations]
    return response


@router.get("", response_model=Page[UserRead])
async def list_users_endpoint(
    session: SessionDep,
    params: ParamsDep,
    current_user: CurrentUserFromHeaders,  # noqa: ARG001
) -> Page[UserRead]:
    page = await apaginate(session, select(User).order_by(User.created_at), params)
    users = page.items
    user_ids = [user.id for user in users]
    organizations_by_user = await list_organizations_for_users(session, user_ids)
    responses: list[UserRead] = []
    for user in users:
        response = UserRead.model_validate(user)
        response.organizations = [
            OrganizationInfo.model_validate(org) for org in organizations_by_user.get(user.id, [])
        ]
        responses.append(response)
    return create_page(responses, total=page.total, params=params)  # type: ignore[return-value]


@router.get("/{user_id}", response_model=UserRead)
@log_activity_decorator(ActivityAction.READ, "user")
async def get_user_endpoint(
    user_id: UUID,
    session: SessionDep,
    current_user: CurrentUserFromHeaders,  # noqa: ARG001
) -> UserRead:
    user = await get_user(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    organizations = await list_organizations_for_user(session, user_id)
    response = UserRead.model_validate(user)
    response.organizations = [OrganizationInfo.model_validate(org) for org in organizations]
    return response


@router.patch("/{user_id}", response_model=UserRead)
@log_activity_decorator(ActivityAction.UPDATE, "user")
async def update_user_endpoint(
    user_id: UUID,
    payload: UserUpdate,
    session: SessionDep,
    current_user: CurrentUserFromHeaders,
) -> UserRead:
    # Check ownership - users can only modify their own profile
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify other users",
        )

    user = await get_user(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    updated = await update_user(session, user, payload)
    organizations = await list_organizations_for_user(session, user_id)
    response = UserRead.model_validate(updated)
    response.organizations = [OrganizationInfo.model_validate(org) for org in organizations]
    return response


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@log_activity_decorator(ActivityAction.DELETE, "user", resource_id_param_name="user_id")
async def delete_user_endpoint(
    user_id: UUID,
    session: SessionDep,
    current_user: CurrentUserFromHeaders,
) -> None:
    # Check ownership - users can only delete their own profile
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete other users",
        )

    user = await get_user(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    await delete_user(session, user)
    await session.commit()


@router.get("/debug/headers")
async def debug_headers(
    x_user_id: Annotated[str | None, Header()] = None,
    x_email: Annotated[str | None, Header()] = None,
) -> dict[str, str | None]:
    """Debug endpoint to verify Oathkeeper headers."""
    return {
        "x_user_id": x_user_id,
        "x_email": x_email,
    }
