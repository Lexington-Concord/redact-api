# Service Integration Patterns

## Overview

The file `redact_api/core/http_client.py` (lines 61-253) contains **commented example patterns** showing how to integrate with external services. These are **REFERENCE IMPLEMENTATIONS**, not active code - uncomment and adapt when integrating with your services.

This guide explains:
- When to use the HTTP client
- How to implement retry and circuit breaker patterns
- How to configure external services
- How to test service integrations
- How to uncomment and adapt the provided examples

---

## When to Use HTTP Client

### ✅ Use HTTP Client For:

1. **Cross-service communication** (microservices)
2. **External API integrations** (payment, email, analytics)
3. **Authentication verification** with auth services
4. **Notifications** via third-party services
5. **Analytics reporting** to external systems

### ❌ Don't Use HTTP Client For:

1. **Internal database queries** - use SQLAlchemy directly
2. **Local function calls** - call async functions directly
3. **File system operations** - use pathlib or aiofiles
4. **Long-running operations** - use background tasks

---

## The HTTP Client

### Basic Usage

```python
from redact_api.core.http_client import http_client

async def call_external_service():
    """Example: Call external service."""
    async with http_client() as client:
        try:
            response = await client.get(
                "https://external-api.example.com/data",
                headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()  # Raise for 4xx/5xx
            data = response.json()
            return data
        except httpx.HTTPStatusError as e:
            logger.error(f"Service error: {e.response.status_code}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request failed: {e}")
            raise
```

### Features

- **Automatic JSON encoding/decoding**
- **Timeout enforcement** (default 30s)
- **Proper async context management**
- **User-Agent header** with app name
- **Error handling** for common scenarios

---

## Pattern 1: Retry with Exponential Backoff

### What It Is

Automatically retry failed requests with increasing delay between attempts.

**When to use**:
- Transient failures (network timeout, temporary service outage)
- Rate limiting (503 Service Unavailable)
- Connection errors

**When NOT to use**:
- Authentication errors (401, 403)
- Bad requests (400, 422)
- Not found (404)

### Installation

```bash
uv pip install tenacity
```

### Implementation

```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    retry_if_result
)
import httpx

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError))
)
async def call_flaky_service() -> dict:
    """Call external service with exponential backoff retry.

    Retries:
    - First failure: wait 2 seconds
    - Second failure: wait 4 seconds
    - Third failure: wait 8 seconds (capped at max=10)
    - Fourth failure: raises exception
    """
    async with http_client() as client:
        response = await client.get("https://flaky-service.example.com/data")
        response.raise_for_status()
        return response.json()
```

### Smart Retry (Don't Retry All Errors)

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((
        httpx.TimeoutException,
        httpx.ConnectError,
        ConnectionError,
    )),
    reraise=True
)
async def call_with_smart_retry() -> dict:
    """Only retry on transient failures."""
    async with http_client() as client:
        response = await client.post(
            "https://api.example.com/action",
            json={"data": "value"}
        )
        # Don't retry on 401, 403, 400, 422
        response.raise_for_status()
        return response.json()
```

### Retry with Result Checking

```python
def is_retryable_response(response: httpx.Response) -> bool:
    """Check if response status is retryable."""
    # Retry on 503, 504, but not 400-level errors
    return response.status_code in (503, 504)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1),
    retry=retry_if_result(lambda result: not result)
)
async def call_with_result_check() -> bool:
    """Retry based on response status."""
    async with http_client() as client:
        try:
            response = await client.get("https://api.example.com/health")
            if is_retryable_response(response):
                return False  # Trigger retry
            response.raise_for_status()
            return True
        except httpx.RequestError:
            return False  # Trigger retry
```

---

## Pattern 2: Circuit Breaker

### What It Is

Fail fast if service is consistently failing. Prevents cascading failures across services.

**How it works**:
1. Normal operation: forward requests
2. Threshold reached (5 failures): open circuit
3. Circuit open: return error immediately without calling service
4. Recovery timeout (60s): try request again
5. If request succeeds: close circuit
6. If request fails: keep circuit open

### Installation

```bash
uv pip install pybreaker
```

### Implementation

```python
from circuitbreaker import circuit
import httpx

@circuit(
    failure_threshold=5,  # Open circuit after 5 failures
    recovery_timeout=60,  # Try recovery after 60 seconds
    expected_exception=httpx.RequestError  # Treat these as failures
)
async def call_with_circuit_breaker(url: str) -> dict:
    """Call external service with circuit breaker.

    Opens circuit (stops calling service) if:
    - 5 consecutive failures occur
    - Waits 60 seconds before trying again

    Best for: APIs that may go down temporarily
    """
    async with http_client() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()
```

### Circuit Breaker with Status Monitoring

```python
from circuitbreaker import CircuitBreakerError

async def call_monitored_service():
    """Call service and monitor circuit state."""
    try:
        data = await call_with_circuit_breaker("https://api.example.com/data")
        return {"success": True, "data": data}
    except CircuitBreakerError:
        # Circuit is open - service is down
        logger.warning("Circuit breaker open - service unavailable")
        return {
            "success": False,
            "error": "Service temporarily unavailable",
            "status": 503
        }
    except Exception as e:
        logger.exception("Service call failed")
        raise
```

### Combining Retry + Circuit Breaker

```python
@circuit(failure_threshold=5, recovery_timeout=60)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5)
)
async def resilient_service_call(url: str) -> dict:
    """Retry transient failures, circuit break on cascade."""
    async with http_client() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()
```

---

## Pattern 3: Service Configuration

### Add to Settings

```python
# In redact_api/core/config.py

from pydantic import BaseSettings, validator

class Settings(BaseSettings):
    """Application settings with external service URLs."""

    # External service URLs
    auth_service_url: str = "https://auth-service.example.com"
    notification_service_url: str = "https://notify.example.com"
    analytics_service_url: str = "https://analytics.example.com"

    # Service credentials
    auth_service_api_key: str = ""  # or use separate env var
    notification_api_key: str = ""

    class Config:
        env_file = ".env"

    @validator("auth_service_url")
    def validate_auth_url(cls, v):
        """Ensure URL is not empty in production."""
        if not v and os.environ.get("ENVIRONMENT") == "production":
            raise ValueError("auth_service_url required in production")
        return v
```

### Set in .env

```bash
# Development
AUTH_SERVICE_URL=http://localhost:8001
NOTIFICATION_SERVICE_URL=http://localhost:8002
ANALYTICS_SERVICE_URL=http://localhost:8003

# Production (or use environment-specific .env files)
# AUTH_SERVICE_URL=https://auth-service.prod.example.com
# NOTIFICATION_SERVICE_URL=https://notify.prod.example.com
```

### Use in Code

```python
from redact_api.core.config import settings

async def verify_token():
    """Use configured service URL."""
    async with http_client() as client:
        response = await client.post(
            f"{settings.auth_service_url}/verify",
            json={"token": token}
        )
        return response.json()
```

---

## Uncommented Examples from http_client.py

The following patterns are commented in `http_client.py` - uncomment and adapt for your services:

### Example 1: Token Verification (Lines 66-95)

```python
# From http_client.py - uncomment to use
async def verify_token_with_auth_service(token: str) -> dict | None:
    '''Verify JWT token with external auth service.

    Returns decoded token claims if valid, None if invalid.

    Requires: settings.auth_service_url in config.py

    Usage:
        claims = await verify_token_with_auth_service(token)
        if claims is None:
            raise HTTPException(status_code=401)
    '''
    async with http_client(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{settings.auth_service_url}/verify",
                json={"token": token},
            )
        except httpx.RequestError:
            return None

        if response.status_code == 200:
            return response.json()
        return None
```

**To use in middleware**:
```python
from redact_api.core.http_client import verify_token_with_auth_service

async def verify_auth(request: Request):
    """Middleware to verify tokens."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    claims = await verify_token_with_auth_service(token)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid token")

    request.state.user_id = claims["sub"]
```

### Example 2: Notification Service (Lines 98-141)

```python
# From http_client.py - uncomment to use
async def send_notification(
    user_id: str,
    message: str,
    channel: str = "email",
) -> bool:
    '''Send notification via external notification service.

    Returns True if sent, False if service unavailable.

    Usage:
        user = await create_user(...)
        await send_notification(user.id, "Welcome!")
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
            return False

        return response.status_code == 202
```

**To use when creating users**:
```python
@router.post("/users")
async def create_user(payload: UserCreate):
    """Create user and send notification."""
    user = await create_user_service(payload)

    # Send notification (non-blocking)
    success = await send_notification(
        user_id=user.id,
        message=f"Welcome {user.name}! Your account is ready."
    )

    if not success:
        logger.warning("Failed to send welcome notification", extra={"user_id": user.id})

    return user
```

### Example 3: Analytics Reporting (Lines 144-190)

```python
# From http_client.py - uncomment to use
async def report_activity(
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
) -> bool:
    '''Send activity report to analytics service.

    Non-blocking: failures don't affect primary request.

    Usage:
        document = await create_document(...)
        await report_activity(
            user_id=current_user.id,
            action="create",
            resource_type="document",
            resource_id=document.id
        )
    '''
    async with http_client(timeout=5.0) as client:
        try:
            from datetime import datetime  # Add this import

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

        return response.status_code in (200, 202)
```

**To use when performing actions**:
```python
@router.post("/documents")
async def create_document(payload: DocumentCreate, current_user: CurrentUserDep):
    """Create document and report activity."""
    document = await create_document_service(payload)

    # Report activity (fire-and-forget)
    asyncio.create_task(
        report_activity(
            user_id=current_user.id,
            action="create",
            resource_type="document",
            resource_id=document.id
        )
    )

    return document
```

---

## Testing Service Integrations

### Unit Test: Mock HTTP Responses

**Installation**:
```bash
uv pip install pytest-httpx
```

**Test**:
```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_verify_token_with_mock(httpx_mock):
    """Test token verification with mocked HTTP response."""
    from redact_api.core.http_client import verify_token_with_auth_service

    # Mock auth service response
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:8001/verify",
        status_code=200,
        json={"sub": "user-123", "email": "user@example.com"}
    )

    # Call function
    claims = await verify_token_with_auth_service("valid-token")

    # Verify result
    assert claims is not None
    assert claims["sub"] == "user-123"

    # Verify request
    request = httpx_mock.get_request()
    assert request.method == "POST"
    assert "verify" in str(request.url)
```

### Integration Test: Test Service

For integration testing, run test versions of external services:

**Using Docker Compose**:
```yaml
# docker-compose.test.yml
version: "3"
services:
  auth-service:
    image: local-auth-service:test
    ports:
      - "8001:8000"
    environment:
      ENVIRONMENT: test

  notification-service:
    image: local-notification-service:test
    ports:
      - "8002:8000"
    environment:
      ENVIRONMENT: test
```

**Test with real services**:
```python
@pytest.mark.asyncio
async def test_verify_token_integration():
    """Test with real test service."""
    from redact_api.core.http_client import verify_token_with_auth_service

    # Requires auth-service running on localhost:8001
    claims = await verify_token_with_auth_service("test-token")

    assert claims is not None
    assert "sub" in claims
```

### Fixture for Mocking

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.fixture
def mock_auth_service():
    """Fixture to mock auth service."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"sub": "user-123"}
        mock_post.return_value = mock_response
        yield mock_post

@pytest.mark.asyncio
async def test_with_fixture(mock_auth_service):
    """Test using mock fixture."""
    from redact_api.core.http_client import verify_token_with_auth_service

    claims = await verify_token_with_auth_service("token")
    assert claims["sub"] == "user-123"
```

---

## Common Patterns Reference

### Pattern: With Timeout

```python
async with http_client(timeout=5.0) as client:  # 5 second timeout
    response = await client.get(url)
```

### Pattern: With Authorization Header

```python
async with http_client() as client:
    response = await client.get(
        url,
        headers={"Authorization": f"Bearer {api_key}"}
    )
```

### Pattern: POST with JSON

```python
async with http_client() as client:
    response = await client.post(
        url,
        json={"key": "value"}
    )
```

### Pattern: Error Handling

```python
async with http_client() as client:
    try:
        response = await client.get(url)
        response.raise_for_status()  # Raise for 4xx/5xx
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e.response.status_code}")
        raise
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise
```

---

## Troubleshooting

### "Connection refused"

**Problem**: Service not running on configured URL

**Solution**:
1. Verify service is running: `curl http://localhost:8001/health`
2. Check `settings.auth_service_url` in `.env`
3. For production, ensure firewall allows traffic

### "Request timeout"

**Problem**: Service is slow or unresponsive

**Solution**:
1. Increase timeout: `http_client(timeout=60.0)`
2. Add retry logic with exponential backoff
3. Add circuit breaker to fail fast
4. Check service health: `curl http://service/health`

### "Circuit breaker open"

**Problem**: Service has been failing consistently

**Solution**:
1. Check external service status
2. Wait for recovery timeout (60s default)
3. Monitor external service logs
4. Increase failure_threshold if service is flaky

### "Invalid JSON response"

**Problem**: Service returned non-JSON response

**Solution**:
```python
try:
    data = response.json()
except ValueError:
    logger.error(f"Invalid JSON: {response.text}")
    raise
```

---

## Summary

To integrate external services:

1. **Add service URL** to settings `.env`
2. **Choose pattern**: Retry (transient), Circuit Breaker (cascading), or plain HTTP
3. **Uncomment example** from `http_client.py` and adapt
4. **Add error handling** with proper logging
5. **Write tests** with mocked HTTP responses
6. **Document** the service integration
7. **Monitor** service health and integration failures

Start simple (plain HTTP), add retry/circuit breaker as needed based on service reliability.
