"""HTTP client for cross-service communication.

NOTE: Example service integration functions (lines 61-253) are commented out.
These are REFERENCE IMPLEMENTATIONS showing patterns - uncomment and adapt
when integrating with external services.

See docs/service_integration_patterns.md for detailed integration guides.

Usage:
    from redact_api.core.http_client import http_client

    async with http_client() as client:
        response = await client.get("https://auth-service/verify",
                                   headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="Unauthorized")
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx

from redact_api.core.config import settings

# HTTP status codes
HTTP_OK = 200
HTTP_ACCEPTED = 202


@asynccontextmanager
async def http_client(timeout: float = 30.0) -> AsyncGenerator[httpx.AsyncClient]:
    """Create HTTP client for service-to-service calls.

    Features:
    - Automatic JSON encoding/decoding
    - Timeout enforcement
    - Proper async context management
    - Error handling for common scenarios

    Args:
        timeout: Request timeout in seconds (default 30)

    Yields:
        AsyncClient configured for cross-service communication

    Example:
        async with http_client() as client:
            try:
                response = await client.get(
                    "https://other-service/api/resource",
                    headers={"Authorization": f"Bearer {token}"}
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Service call failed: {e.response.status_code}")
                raise
    """
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": f"redact_api/{settings.environment}"},
    ) as client:
        yield client


# EXAMPLE PATTERNS (commented to avoid type errors):
# These patterns show how to call external services, but are not active code.
# Uncomment and add corresponding settings when implementing service integrations.

"""
async def verify_token_with_auth_service(
    token: str,
) -> dict | None:
    '''Verify JWT token with external auth service.

    Returns decoded token claims if valid, None if invalid.

    Requires: settings.auth_service_url in config.py

    Example usage in auth middleware:
        claims = await verify_token_with_auth_service(token)
        if claims is None:
            raise HTTPException(status_code=401, detail="Invalid token")

        user_id = claims["sub"]
        # Proceed with authenticated request
    '''
    async with http_client(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{settings.auth_service_url}/verify",
                json={"token": token},
            )
        except httpx.RequestError:
            # Log error and fail open or closed based on business logic
            return None

        if response.status_code == HTTP_OK:
            return response.json()
        return None


async def send_notification(
    user_id: str,
    message: str,
    channel: str = "email",
) -> bool:
    '''Send notification via external notification service.

    Returns True if sent, False if service unavailable.
    Used for event-driven communication (user created, org deleted, etc).

    Requires: settings.notification_service_url in config.py

    Example usage in user creation endpoint:
        user = await create_user(...)
        await send_notification(
            user_id=user.id,
            message=f"Welcome {user.name}! Your account is ready.",
            channel="email"
        )

    Example usage in organization deletion:
        await delete_organization(org_id)
        for member in members:
            await send_notification(
                user_id=member.user_id,
                message=f"Organization {org.name} has been deleted.",
                channel="email"
            )
    '''
    async with http_client(timeout=10.0) as client:
        try:
            response = await client.post(
                f"{settings.notification_service_url}/send",
                json={
                    "user_id": user_id,
                    "message": message,
                    "channel": channel,
                },
            )
        except httpx.RequestError:
            # Don't fail primary operation on notification failure
            return False

        return response.status_code == HTTP_ACCEPTED


async def report_activity(
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
) -> bool:
    '''Send activity report to analytics service.

    Non-blocking: failures don't affect primary request.

    Requires: settings.analytics_service_url in config.py

    Example usage in API endpoints:
        # After creating a document
        document = await document_service.create(...)
        await report_activity(
            user_id=current_user.id,
            action="create",
            resource_type="document",
            resource_id=document.id
        )

        # After deleting an organization
        await organization_service.delete(org_id)
        await report_activity(
            user_id=current_user.id,
            action="delete",
            resource_type="organization",
            resource_id=org_id
        )
    '''
    async with http_client(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{settings.analytics_service_url}/events",
                json={
                    "user_id": user_id,
                    "action": action,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
        except httpx.RequestError:
            return False

        return response.status_code in (HTTP_OK, HTTP_ACCEPTED)
"""


# CIRCUIT BREAKER PATTERN (advanced, commented example):
"""
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=60)
async def call_external_service(url: str) -> dict:
    '''Call external service with circuit breaker.

    - Fails fast after 5 consecutive failures
    - Recovers after 60 seconds
    - Prevents cascading failures

    Install: pip install pybreaker

    Example usage:
        try:
            data = await call_external_service("https://external-api/resource")
            # Process data
        except CircuitBreakerError:
            # Service is down, circuit is open
            logger.error("External service circuit breaker open")
            # Return cached data or fail gracefully
    '''
    async with http_client() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()
"""

# RETRY PATTERN (advanced, commented example):
"""
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def call_with_retry(url: str) -> dict:
    '''Call external service with exponential backoff retry.

    - Retries up to 3 times
    - Waits 2s, 4s, 8s between retries
    - Useful for transient network failures

    Install: pip install tenacity

    Example usage:
        try:
            data = await call_with_retry("https://flaky-service/data")
            # Process data
        except Exception as e:
            # All retries failed
            logger.error(f"Service call failed after 3 retries: {e}")
            raise
    '''
    async with http_client() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()
"""
