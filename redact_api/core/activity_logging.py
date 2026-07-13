"""Activity logging decorator for centralizing audit trail recording.

Transaction Model
-----------------
Activity logging supports two transaction patterns:

1. **Transactional (with session)**: Activity log is added to caller's session.
   Caller commits the activity log alongside the primary operation.

2. **Fire-and-forget (without session)**: Activity log is committed immediately
   in its own transaction, independent of caller's transaction.

Both patterns are best-effort: logging failures never interrupt the primary operation.

Security Notes
--------------
- Never log passwords, tokens, API keys, or other secrets in details field
- Sanitize user input before logging
- Activity logs should only contain non-sensitive metadata
"""

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from redact_api.core.config import settings
from redact_api.core.logging import get_logging_context
from redact_api.db.session import async_session_maker
from redact_api.models.activity_log import ActivityAction, ActivityLog

LOGGER = logging.getLogger(__name__)


async def log_activity(
    action: ActivityAction,
    resource_type: str,
    resource_id: UUID | None = None,
    details: dict[str, Any] | None = None,
    *,
    session: AsyncSession | None = None,
) -> None:
    """Log an activity to the audit trail.

    This is a best-effort function that will not raise exceptions if logging
    fails. Logging failures are logged to the application logger but never
    interrupt the primary operation.

    Transaction Patterns:
        - **With session**: Activity log is added to provided session. Caller
          is responsible for committing the transaction. Use this pattern in
          API endpoints to ensure activity log is committed atomically with
          the primary operation.

        - **Without session**: Activity log is committed immediately in its own
          transaction (fire-and-forget). Use this pattern for background tasks
          or when transactional consistency with the primary operation is not
          required.

    Args:
        action: ActivityAction enum for the audit log
        resource_type: String identifier for resource type (e.g., "user",
            "organization")
        resource_id: UUID of the resource being acted upon (optional)
        details: Additional context to store as JSON (optional)
        session: AsyncSession for database operations (optional). If None,
            creates and commits in a new session immediately.

    Examples:
        Transactional pattern (API endpoint):
            >>> async def create_user(
            ...     session: AsyncSession, payload: UserCreate
            ... ) -> User:
            ...     user = User(**payload.model_dump())
            ...     session.add(user)
            ...     await session.commit()
            ...     await log_activity(
            ...         action=ActivityAction.CREATE,
            ...         resource_type="user",
            ...         resource_id=user.id,
            ...         session=session,
            ...     )
            ...     return user

        Fire-and-forget pattern (background task):
            >>> async def cleanup_old_records() -> None:
            ...     # Clean up records...
            ...     await log_activity(
            ...         action=ActivityAction.DELETE,
            ...         resource_type="record",
            ...         details={"count": records_deleted},
            ...     )

    Security Notes:
        - Never log passwords, tokens, API keys, or other secrets in details
        - Sanitize user input before including in details
        - Activity logs should only contain non-sensitive metadata

    Testing Notes:
        Tests should verify:
        - Activity is logged on success (check database)
        - Activity NOT logged when settings.activity_logging_enabled is False
        - Primary operation not interrupted if logging fails
        - Transactional pattern: activity committed with primary operation
        - Fire-and-forget pattern: activity committed immediately
    """
    if not settings.activity_logging_enabled:
        return

    try:
        activity = ActivityLog(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )

        if session is not None:
            # Transactional: add to caller's session, caller commits
            session.add(activity)
            context = get_logging_context()
            LOGGER.info(
                "activity_logged",
                extra={
                    **context,
                    "action": action.value,
                    "resource_type": resource_type,
                    "resource_id": str(resource_id) if resource_id else None,
                    "transaction_mode": "transactional",
                },
            )
        else:
            # Fire-and-forget: commit immediately in own transaction
            async with async_session_maker() as temp_session:
                temp_session.add(activity)
                await temp_session.commit()
                context = get_logging_context()
                LOGGER.info(
                    "activity_logged",
                    extra={
                        **context,
                        "action": action.value,
                        "resource_type": resource_type,
                        "resource_id": str(resource_id) if resource_id else None,
                        "transaction_mode": "fire_and_forget",
                    },
                )
    except Exception:
        """Best-Effort Exception Handling

        Rationale for Bare Exception Clause:
        =====================================
        Activity logging is a best-effort service. If logging fails for ANY reason,
        we MUST NOT interrupt the primary operation. This requires catching all
        possible exceptions:

        1. Database Errors: Connection failures, deadlocks, constraint violations
        2. Validation Errors: Invalid ActivityLog data, serialization failures
        3. Async Errors: Task cancellation, event loop issues
        4. Unexpected Errors: Any exception we didn't anticipate

        Using bare `except Exception:` (not `except BaseException:`) ensures we:
        - Catch all application errors (safe to suppress)
        - Still respect KeyboardInterrupt and SystemExit (allow graceful shutdown)
        - Log the error for debugging without failing the user request

        Alternative approaches rejected:
        - Catching specific exceptions: Would miss unexpected errors
        - Re-raising: Would break the primary operation
        - Silent ignoring: Would hide logging bugs in production

        This pattern is appropriate for background/fire-and-forget operations where
        the side effect (activity log) is less critical than the primary operation
        (user request handling).
        """
        # Log error without propagating to caller
        context = get_logging_context()
        LOGGER.exception(
            "activity_logging_failed",
            extra={
                **context,
                "action": action.value,
                "resource_type": resource_type,
                "resource_id": str(resource_id) if resource_id else None,
            },
        )


def log_activity_decorator(
    action: ActivityAction,
    resource_type: str,
    resource_id_param_name: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to automatically log API endpoint activity.

    Wraps an endpoint to record activity after successful execution.
    Handles response model inspection to extract resource IDs automatically,
    with fallback to path parameters for endpoints that return no response body.

    Transaction Model:
        The decorator extracts the session from endpoint kwargs and passes it to
        log_activity(). The activity log is added to the same session as the
        primary operation, ensuring transactional consistency. The endpoint is
        responsible for committing the session, which will commit both the primary
        operation and the activity log atomically.

        If the endpoint raises an exception before committing, the entire transaction
        (including the activity log) will be rolled back automatically by the session
        dependency's exception handler.

    Args:
        action: ActivityAction enum for the audit log
        resource_type: String identifier for resource type (e.g., "user",
            "organization")
        resource_id_param_name: Optional name of the path parameter containing
            the resource ID (e.g., "user_id", "organization_id"). Used when
            response body doesn't contain an ID field (e.g., DELETE endpoints
            returning 204 No Content). If provided, decorator will extract the
            resource ID from kwargs using this parameter name as a fallback.

    Returns:
        Decorator function for API endpoints

    Examples:
        CREATE action with automatic ID extraction from response:
            >>> @router.post("", response_model=UserRead, status_code=201)
            ... @log_activity_decorator(ActivityAction.CREATE, "user")
            ... async def create_user_endpoint(
            ...     payload: UserCreate,
            ...     session: SessionDep,
            ... ) -> User:
            ...     user = User(**payload.model_dump())
            ...     session.add(user)
            ...     await session.commit()
            ...     # Activity log committed atomically with user creation
            ...     # resource_id extracted from response.id
            ...     return user

        DELETE action with resource_id from path parameter:
            >>> @router.delete("/{user_id}", status_code=204)
            ... @log_activity_decorator(
            ...     ActivityAction.DELETE, "user",
            ...     resource_id_param_name="user_id"
            ... )
            ... async def delete_user_endpoint(
            ...     user_id: UUID,
            ...     session: SessionDep,
            ... ) -> None:
            ...     user = await get_user(session, user_id)
            ...     await delete_user(session, user)
            ...     # Activity log committed atomically with user deletion
            ...     # resource_id extracted from path parameter user_id

        UPDATE action (automatic extraction from response):
            >>> @router.patch("/{user_id}", response_model=UserRead)
            ... @log_activity_decorator(ActivityAction.UPDATE, "user")
            ... async def update_user_endpoint(
            ...     user_id: UUID,
            ...     payload: UserUpdate,
            ...     session: SessionDep,
            ... ) -> User:
            ...     user = await get_user(session, user_id)
            ...     user.update(**payload.model_dump(exclude_unset=True))
            ...     await session.commit()
            ...     # Activity log committed atomically with user update
            ...     return user

    Security Notes:
        - Never log passwords, tokens, API keys, or other secrets
        - The decorator extracts only the 'id' field from response objects
        - Only path parameter IDs are extracted (not user input from body/query)
        - Additional details should be logged explicitly via log_activity() if needed
        - Sanitize user input before including in activity log details

    Error Handling:
        - If endpoint raises before commit: transaction rolls back, no activity logged
        - If log_activity() fails: error logged but endpoint execution continues
        - Activity logging failures never interrupt the primary operation
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Inner decorator that wraps the endpoint function.

        Args:
            func: The endpoint function to wrap

        Returns:
            Wrapped function with activity logging
        """

        @wraps(func)
        async def wrapper(*args: object, **kwargs: object) -> Any:  # noqa: ANN401
            """Execute endpoint and log activity on success.

            Args:
                *args: Positional arguments passed to endpoint
                **kwargs: Keyword arguments passed to endpoint

            Returns:
                Result from wrapped endpoint function
            """
            # Extract session dependency from kwargs
            session: AsyncSession | None = kwargs.get("session")  # type: ignore[assignment]

            # Execute endpoint function
            result = await func(*args, **kwargs)

            # Extract resource_id from response or path parameter
            resource_id: UUID | None = None

            # First, try to extract from response body (for CREATE/READ/UPDATE)
            if result is not None:
                if hasattr(result, "id"):
                    resource_id = getattr(result, "id", None)
                elif isinstance(result, dict) and "id" in result:
                    resource_id = result["id"]

            # Fallback: extract from path parameter if response didn't have ID
            # (for DELETE endpoints returning 204 No Content)
            if resource_id is None and resource_id_param_name is not None:
                resource_id = kwargs.get(resource_id_param_name)  # type: ignore[assignment]

            # Log activity (best-effort, doesn't fail request)
            if session is not None:
                await log_activity(
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    session=session,
                )

            return result

        return wrapper

    return decorator
