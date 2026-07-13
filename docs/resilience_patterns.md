# Resilience Patterns for External Service Calls

Guide for implementing resilience patterns when calling external services (auth providers, storage, payment processors, etc.).

## Overview

External services are inherently unreliable. Network might be slow, service might be down, or authorization might fail. Resilience patterns prevent cascading failures and improve user experience.

### Key Patterns

1. **Retry**: Retry failed requests with exponential backoff
2. **Circuit Breaker**: Stop calling failing service temporarily
3. **Timeout**: Fail fast if service doesn't respond
4. **Fallback**: Provide graceful degradation
5. **Bulkhead**: Isolate resource pools

## Circuit Breaker Pattern

### Concept

A circuit breaker has three states:

```
┌─────────────────────┐
│   CLOSED (normal)   │  All requests pass through
│ Service working OK  │
└──────────┬──────────┘
           │ failures > threshold
           ↓
┌─────────────────────┐
│  OPEN (failing)     │  All requests fail immediately (no call)
│  Service not usable │
└──────────┬──────────┘
           │ timeout expires
           ↓
┌─────────────────────┐
│HALF-OPEN (testing)  │  Allow single request to test recovery
│ Testing recovery    │
└─────────────────────┘
```

### Implementation with Tenacity

```python
# Install: pip install tenacity

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
)
async def call_auth_provider(token: str) -> dict:
    """Call auth provider with automatic retry."""
    # Will retry up to 3 times with exponential backoff
    # On connection/timeout errors
    return await auth_provider.validate_token(token)
```

### Implementation with Circuit Breaker Library

```python
# Install: pip install pybreaker

from pybreaker import CircuitBreaker

# Create circuit breaker for auth provider
auth_breaker = CircuitBreaker(
    fail_max=5,           # Open after 5 failures
    reset_timeout=60,     # Try recovery after 60 seconds
    name="auth_provider",
)

async def validate_token_with_breaker(token: str) -> dict | None:
    """Validate token with circuit breaker protection."""
    try:
        with auth_breaker:
            return await auth_provider.validate_token(token)
    except auth_breaker.CircuitBreakerListener:
        # Circuit is open - service unavailable
        LOGGER.warning("Auth provider circuit breaker open")
        return None  # Return None or cached/default value
```

### Implementation with Custom Decorator

```python
import asyncio
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Awaitable, Callable, TypeVar

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class AsyncCircuitBreaker:
    """Simple async circuit breaker implementation."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type[Exception] = Exception,
        name: str = "circuit_breaker",
    ):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening
            recovery_timeout: Seconds before trying to recover
            expected_exception: Exception type to trigger breaker
            name: Name for logging
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.name = name
        self.failure_count = 0
        self.last_failure_time: datetime | None = None
        self.state = CircuitState.CLOSED

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute function with circuit breaker protection.

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result from function

        Raises:
            Exception: Original exception or CircuitBreakerOpen
        """
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout elapsed
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                LOGGER.info(f"{self.name}: attempting recovery")
            else:
                raise CircuitBreakerOpen(
                    f"{self.name}: circuit breaker is open"
                )

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as exc:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if recovery timeout has elapsed."""
        if not self.last_failure_time:
            return False
        elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout

    def _on_success(self) -> None:
        """Handle successful call."""
        if self.state == CircuitState.HALF_OPEN:
            LOGGER.info(f"{self.name}: recovered, closing circuit")
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            LOGGER.warning(
                f"{self.name}: circuit breaker opened after "
                f"{self.failure_count} failures"
            )


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""
    pass


# Usage in service
auth_breaker = AsyncCircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60,
    expected_exception=ConnectionError,
    name="auth_provider",
)

async def validate_token(token: str) -> dict:
    """Validate token with circuit breaker."""
    return await auth_breaker.call(
        auth_provider.validate_token,
        token,
    )
```

## Retry Pattern

### Exponential Backoff

```python
import asyncio
from typing import TypeVar

T = TypeVar("T")

async def retry_with_backoff(
    func,
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
):
    """Retry async function with exponential backoff.

    Args:
        func: Async function to call
        max_attempts: Maximum number of attempts
        initial_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries
        backoff_factor: Multiply delay by this each retry

    Returns:
        Result from function

    Raises:
        Exception: Last exception if all retries fail
    """
    delay = initial_delay
    last_exception = None

    for attempt in range(max_attempts):
        try:
            return await func()
        except Exception as exc:
            last_exception = exc
            if attempt < max_attempts - 1:
                LOGGER.warning(
                    f"Attempt {attempt + 1} failed, retrying in {delay}s",
                    extra={"error": str(exc), "attempt": attempt + 1},
                )
                await asyncio.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)

    raise last_exception or Exception("All retries failed")


# Usage
async def get_user_from_auth_provider(user_id: str) -> dict:
    """Get user from auth provider with retries."""
    return await retry_with_backoff(
        lambda: auth_provider.get_user(user_id),
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
    )
```

## Timeout Pattern

```python
import asyncio

async def call_with_timeout(
    coro,
    timeout_seconds: float = 5.0,
) -> Any:
    """Call async function with timeout.

    Args:
        coro: Async coroutine to execute
        timeout_seconds: Timeout in seconds

    Returns:
        Result from coroutine

    Raises:
        asyncio.TimeoutError: If timeout exceeded
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        LOGGER.error(
            "Call timed out",
            extra={"timeout_seconds": timeout_seconds},
        )
        raise


# Usage
async def validate_token_with_timeout(token: str) -> dict:
    """Validate token with 5 second timeout."""
    return await call_with_timeout(
        auth_provider.validate_token(token),
        timeout_seconds=5.0,
    )
```

## Combined Pattern: Retry + Timeout + Fallback

```python
async def resilient_auth_check(
    token: str,
    fallback_valid: bool = False,
) -> bool:
    """Check authentication with full resilience.

    Combines:
    1. Timeout to fail fast
    2. Retry with backoff for transient errors
    3. Fallback when service unavailable

    Args:
        token: JWT token to validate
        fallback_valid: Assume valid if service unavailable

    Returns:
        True if token valid, False otherwise
    """
    try:
        # Retry with backoff and timeout
        return await retry_with_backoff(
            lambda: call_with_timeout(
                auth_provider.validate_token(token),
                timeout_seconds=3.0,
            ),
            max_attempts=3,
            initial_delay=0.5,
        )
    except asyncio.TimeoutError:
        LOGGER.error("Auth check timeout")
        return fallback_valid
    except ConnectionError:
        LOGGER.error("Auth provider unavailable")
        return fallback_valid
    except Exception as exc:
        LOGGER.error(f"Auth check failed: {exc}")
        return False
```

## Implementation in FastAPI

### Auth Provider Integration

```python
# core/auth.py

from redact_api.core.resilience import AsyncCircuitBreaker

# Create circuit breaker for remote auth provider
remote_auth_breaker = AsyncCircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60,
    expected_exception=(ConnectionError, TimeoutError),
    name="remote_auth_provider",
)

async def validate_token_remote(token: str) -> dict:
    """Validate token with remote auth provider.

    Uses circuit breaker to prevent cascading failures.
    Falls back to local JWT validation if unavailable.
    """
    try:
        return await remote_auth_breaker.call(
            call_with_timeout,
            auth_provider.validate_token(token),
            timeout_seconds=5.0,
        )
    except CircuitBreakerOpen:
        LOGGER.warning("Remote auth unavailable, using local validation")
        return validate_token_local(token)  # Fallback
```

### Storage Service Integration

```python
# core/storage.py

storage_breaker = AsyncCircuitBreaker(
    failure_threshold=10,
    recovery_timeout=120,
    expected_exception=(ConnectionError, TimeoutError),
    name="storage_service",
)

async def upload_with_resilience(
    document_id: UUID,
    file_data: bytes,
    content_type: str,
) -> str:
    """Upload file with circuit breaker protection."""
    try:
        return await storage_breaker.call(
            call_with_timeout,
            storage.upload(document_id, file_data, content_type),
            timeout_seconds=30.0,
        )
    except CircuitBreakerOpen:
        raise HTTPException(
            status_code=503,
            detail="Storage service temporarily unavailable",
        )
```

## Monitoring Circuit Breaker Health

```python
@router.get("/health/breakers")
async def breaker_health() -> dict:
    """Check circuit breaker status."""
    return {
        "auth_provider": {
            "state": auth_breaker.state.value,
            "failures": auth_breaker.failure_count,
        },
        "storage": {
            "state": storage_breaker.state.value,
            "failures": storage_breaker.failure_count,
        },
    }
```

## Best Practices

### 1. Choose Appropriate Thresholds

```python
# For critical auth service: fail slow, recover quick
auth_breaker = AsyncCircuitBreaker(
    failure_threshold=10,  # More tolerance
    recovery_timeout=30,   # Try recovery soon
)

# For non-critical storage: fail fast, long recovery
storage_breaker = AsyncCircuitBreaker(
    failure_threshold=3,   # Less tolerance
    recovery_timeout=300,  # Long before retry
)
```

### 2. Log Transitions

```python
async def call_with_logging(breaker: AsyncCircuitBreaker, func):
    """Call with detailed logging."""
    state_before = breaker.state
    try:
        result = await breaker.call(func)
        if state_before != CircuitState.CLOSED:
            LOGGER.info(f"Service recovered: {breaker.name}")
        return result
    except CircuitBreakerOpen:
        LOGGER.warning(f"Service unavailable: {breaker.name}")
        raise
```

### 3. Provide Fallbacks

```python
# Always have a fallback for critical operations
async def get_user_avatar(user_id: UUID) -> str:
    """Get user avatar with fallback."""
    try:
        return await storage_breaker.call(
            storage.get_url,
            f"avatars/{user_id}",
        )
    except (CircuitBreakerOpen, Exception):
        # Return default avatar
        return "https://example.com/default-avatar.png"
```

## See Also

- [Testing External Services](testing_external_services.md) - Mocking external calls
- [Activity Logging](activity_logging.md) - Log resilience events
