"""Background task utilities for asynchronous, non-blocking operations.

This module provides patterns for running background tasks in FastAPI applications:
1. Fire-and-forget tasks using asyncio.create_task()
2. Distributed task patterns (Celery/RQ - commented)

Background tasks should:
- Handle their own exceptions gracefully
- Use structured logging with context (user_id, org_id, etc.)
- Not block the HTTP response
- Be idempotent where possible
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

# Background task constants
ARCHIVE_DEFAULT_DAYS = 90
EMAIL_TASK_TIMEOUT_SECONDS = 30
REPORT_GENERATION_TIMEOUT_SECONDS = 300


async def send_welcome_email_task(user_id: UUID, email: str) -> None:
    """Send welcome email to new user (fire-and-forget background task).

    This task runs asynchronously without blocking the API response. Failures are
    logged but do not affect the user creation process.

    Args:
        user_id: UUID of the newly created user
        email: Email address to send welcome message to

    Example:
        # In endpoint:
        user = await create_user(session, payload)
        asyncio.create_task(send_welcome_email_task(user.id, user.email))
        return user
    """
    try:
        logger.info(
            "sending_welcome_email",
            extra={"user_id": str(user_id), "email": email},
        )

        # TODO: IMPLEMENT - This is a placeholder showing error handling structure
        # Replace with actual email service integration (SendGrid, SES, Mailgun, SMTP)
        # See: docs/implementing_email_service.md for integration guide
        #
        # Simulate email sending (replace with actual email service)
        # await email_service.send_template(
        #     to=email,
        #     template="welcome",
        #     context={"user_id": str(user_id)}
        # )
        await asyncio.sleep(0.1)  # Placeholder - remove this line when implementing

        logger.info(
            "welcome_email_sent",
            extra={"user_id": str(user_id), "email": email},
        )
    except Exception:
        error_msg = "Failed to send welcome email"
        logger.exception(
            error_msg,
            extra={"user_id": str(user_id), "email": email},
        )


async def archive_old_activity_logs_task(org_id: UUID, days_older_than: int) -> None:
    """Archive activity logs older than specified days (background task).

    This task can be triggered manually or scheduled via cron. It runs in the
    background to avoid blocking API responses.

    Args:
        org_id: UUID of the organization whose logs to archive
        days_older_than: Archive logs older than this many days (default: 90)

    Example:
        # In endpoint or scheduled job:
        asyncio.create_task(
            archive_old_activity_logs_task(org_id, days_older_than=90)
        )
    """
    try:
        logger.info(
            "archiving_old_activity_logs",
            extra={
                "org_id": str(org_id),
                "days_older_than": days_older_than,
            },
        )

        # TODO: IMPLEMENT - This is a placeholder showing error handling structure
        # Replace with actual log archival strategy (S3, cold storage table, or deletion)
        # See: docs/implementing_log_archival.md for archival patterns and options
        #
        # Simulate archival process (replace with actual implementation)
        # from datetime import datetime, timedelta
        # cutoff_date = datetime.utcnow() - timedelta(days=days_older_than)
        # await archive_service.archive_logs(org_id, cutoff_date)
        await asyncio.sleep(0.1)  # Placeholder - remove this line when implementing

        logger.info(
            "activity_logs_archived",
            extra={
                "org_id": str(org_id),
                "days_older_than": days_older_than,
            },
        )
    except Exception:
        error_msg = "Failed to archive activity logs"
        logger.exception(
            error_msg,
            extra={
                "org_id": str(org_id),
                "days_older_than": days_older_than,
            },
        )


async def generate_activity_report_task(org_id: UUID, period: str) -> None:
    """Generate activity report for organization (background task).

    This task generates a report of organization activity over a specified period
    and typically emails it or stores it for download.

    Args:
        org_id: UUID of the organization to generate report for
        period: Time period for report (e.g., "weekly", "monthly", "quarterly")

    Example:
        # In endpoint or scheduled job:
        asyncio.create_task(
            generate_activity_report_task(org_id, period="monthly")
        )
    """
    try:
        logger.info(
            "generating_activity_report",
            extra={"org_id": str(org_id), "period": period},
        )

        # TODO: IMPLEMENT - This is a placeholder showing error handling structure
        # Replace with actual report generation and delivery (PDF, CSV, or email)
        # See: docs/implementing_reports.md for report generation patterns
        #
        # Simulate report generation (replace with actual implementation)
        # report_data = await analytics_service.generate_report(org_id, period)
        # await report_storage.save(org_id, report_data)
        # await email_service.send_report(org_id, report_data)
        await asyncio.sleep(0.1)  # Placeholder - remove this line when implementing

        logger.info(
            "activity_report_generated",
            extra={"org_id": str(org_id), "period": period},
        )
    except Exception:
        error_msg = "Failed to generate activity report"
        logger.exception(
            error_msg,
            extra={"org_id": str(org_id), "period": period},
        )


# ============================================================================
# OPTIONAL: Distributed Task Queue Pattern (Celery/RQ)
# ============================================================================
#
# For production deployments with multiple worker processes or servers, consider
# using a distributed task queue like Celery or RQ instead of asyncio.create_task().
#
# Benefits of distributed queues:
# - Tasks survive application restarts
# - Horizontal scaling across multiple workers
# - Task retry with exponential backoff
# - Task result tracking and monitoring
# - Priority queues and rate limiting
#
# Example with Celery:
#
# from celery import Celery
#
# # Configure Celery (typically in separate config file)
# celery_app = Celery(
#     'myapp',
#     broker='redis://localhost:6379/0',
#     backend='redis://localhost:6379/1'
# )
#
# celery_app.conf.update(
#     task_serializer='json',
#     accept_content=['json'],
#     result_serializer='json',
#     timezone='UTC',
#     enable_utc=True,
# )
#
# # Define tasks
# @celery_app.task(bind=True, max_retries=3)
# def send_welcome_email(self, user_id: str, email: str) -> dict:
#     """Send welcome email via Celery worker.
#
#     Args:
#         self: Celery task instance (for retry)
#         user_id: UUID as string
#         email: Email address
#
#     Returns:
#         Status dict with result
#     """
#     try:
#         logger.info(
#             "sending_welcome_email",
#             extra={"user_id": user_id, "email": email}
#         )
#         # email_service.send(email, "Welcome!")
#         return {"status": "sent", "user_id": user_id}
#     except Exception as exc:
#         logger.exception("Failed to send email", extra={"user_id": user_id})
#         # Retry with exponential backoff
#         raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
#
# # In endpoint:
# @router.post("/users", response_model=UserRead)
# async def create_user_endpoint(payload: UserCreate, session: SessionDep):
#     user = await create_user(session, payload)
#
#     # Enqueue task to Celery worker (non-blocking)
#     send_welcome_email.delay(str(user.id), user.email)
#
#     return UserRead.model_validate(user)
#
# # Running Celery worker:
# # celery -A myapp.core.background_tasks worker --loglevel=info
#
# Resources:
# - Celery: https://docs.celeryq.dev/
# - RQ (simpler alternative): https://python-rq.org/
# - FastAPI + Celery: https://fastapi.tiangolo.com/tutorial/background-tasks/
