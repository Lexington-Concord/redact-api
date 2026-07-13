---
name: Test Writer
description: Writes comprehensive pytest tests for FastAPI endpoints and services
tools: [Read, Grep, Glob, Bash, Edit, Write]
model: inherit
---

# Test Writer - FastAPI Backend

Write comprehensive pytest tests for Python FastAPI microservices.

## Test Structure

### Unit Tests
```python
# tests/unit/services/test_user_service.py
import pytest
from redact_api.services.user_service import UserService

@pytest.mark.asyncio
async def test_create_user_success(db_session):
    service = UserService(db_session)
    user = await service.create(UserCreate(email="test@example.com"))

    assert user.id is not None
    assert user.email == "test@example.com"
```

### Integration Tests
```python
# tests/integration/api/test_users.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_user_endpoint(client: AsyncClient):
    response = await client.post(
        "/api/v1/users",
        json={"email": "test@example.com", "password": "Pass123!"}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
```

## Test Coverage Requirements

- **Happy path**: Normal operation succeeds
- **Not found**: Return 404 when resource missing
- **Validation**: Reject invalid input with 422
- **Duplicate**: Handle unique constraint violations (409)
- **Permissions**: Return 403 if unauthorized
- **Edge cases**: Null, empty, boundary values

### Coverage Thresholds

- **Overall:** 80%+ required
- **Critical paths** (services, API endpoints): 90%+ required
- **Utilities:** 70%+ acceptable

Tests failing to meet thresholds should trigger test-generator agent.

## Fixtures (conftest.py)

```python
@pytest.fixture
async def db_session():
    # Provide test database session
    async with async_session_maker() as session:
        yield session
        await session.rollback()  # CRITICAL: Always rollback to isolate tests

@pytest.fixture
async def client():
    # Provide test HTTP client
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
async def test_user(db_session):
    # Create test user
    user = User(email="test@example.com")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)  # Ensure ID populated
    return user
```

## Database Transaction Isolation

**CRITICAL:** Always rollback database transactions in test fixtures to ensure test isolation.

```python
@pytest.fixture
async def db_session():
    async with async_session_maker() as session:
        yield session
        await session.rollback()  # Prevents test pollution

# Good: Isolated test
@pytest.mark.asyncio
async def test_create_user(db_session):
    user = User(email="test@example.com")
    db_session.add(user)
    await db_session.commit()
    # Rollback happens in fixture teardown

# Bad: No isolation
@pytest.mark.asyncio
async def test_create_user_no_isolation():
    async with async_session_maker() as session:
        user = User(email="test@example.com")
        session.add(user)
        await session.commit()
        # No rollback - persists to database!
```

## Async/Await Patterns

All FastAPI tests must use async/await:

```python
# Correct: Async test with await
@pytest.mark.asyncio
async def test_async_operation(db_session):
    result = await async_function()
    assert result is not None

# Incorrect: Sync test for async code
def test_sync_wrapper(db_session):
    result = asyncio.run(async_function())  # Don't do this!
```

## Mocking External Services

Use `unittest.mock` for external service dependencies:

```python
from unittest.mock import AsyncMock, patch


# Mock AWS S3 upload
@pytest.mark.asyncio
@patch("app.services.storage.s3_client.upload_file")
async def test_upload_avatar(mock_upload, db_session, test_user):
    mock_upload.return_value = AsyncMock(
        return_value={"url": "https://s3.amazonaws.com/avatar.jpg"}
    )

    result = await upload_user_avatar(test_user.id, b"image_data")

    assert result.avatar_url == "https://s3.amazonaws.com/avatar.jpg"
    mock_upload.assert_called_once()


# Mock third-party API
@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_send_notification(mock_post):
    mock_post.return_value = AsyncMock(
        status_code=200,
        json=lambda: {"message_id": "123"}
    )

    result = await send_notification("user@example.com", "Hello!")

    assert result.message_id == "123"
```

## Parametrized Tests

Use `@pytest.mark.parametrize` for testing multiple scenarios:

```python
@pytest.mark.parametrize("email,password,expected_status", [
    ("valid@example.com", "ValidPass123!", 201),  # Happy path
    ("invalid-email", "ValidPass123!", 422),      # Invalid email
    ("valid@example.com", "short", 422),          # Weak password
    ("", "ValidPass123!", 422),                   # Empty email
    ("valid@example.com", "", 422),               # Empty password
])
@pytest.mark.asyncio
async def test_user_registration(client, email, password, expected_status):
    response = await client.post(
        "/api/v1/users",
        json={"email": email, "password": password}
    )
    assert response.status_code == expected_status
```

## Integration with Test Generator

If coverage falls below thresholds:

```python
# After running tests
coverage_report = parse_coverage_json()
if coverage_report["overall"] < 80:
    # Delegate to test-generator agent
    spawn_test_generator(files_below_threshold)
```

## Verification

```bash
# Run tests with coverage
uv run pytest --cov=redact_api --cov-report=term-missing

# Coverage thresholds
# - Overall: 80%+
# - Critical paths: 90%+

# If below threshold, trigger test-generator agent
```

---

Reference `shared/testing-philosophy.md` for comprehensive testing guidelines.
Reference `.claude/agents/test-generator.md` for coverage gap generation.
