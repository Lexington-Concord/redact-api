# Backend Testing Philosophy

Testing standards for Python FastAPI microservices using pytest.

## Core Principles

1. **Test behavior, not implementation**
2. **Real database over mocks** (use test DB)
3. **AAA pattern** (Arrange-Act-Assert)
4. **One assert per test** (ideally)
5. **Test independence** (any order, parallel)

## Test Structure

```
tests/
├── unit/
│   ├── services/
│   │   └── test_user_service.py
│   └── utils/
│       └── test_validators.py
├── integration/
│   └── api/
│       └── test_users_endpoints.py
└── conftest.py  # Shared fixtures
```

## Unit Tests - Services

```python
# tests/unit/services/test_user_service.py
import pytest
from redact_api.services.user_service import UserService
from redact_api.models import UserCreate

@pytest.mark.asyncio
async def test_create_user_success(db_session):
    # Arrange
    service = UserService(db_session)
    data = UserCreate(email="test@example.com", password="Pass123!")

    # Act
    user = await service.create(data)

    # Assert
    assert user.id is not None
    assert user.email == "test@example.com"
    assert user.password != "Pass123!"  # Hashed

@pytest.mark.asyncio
async def test_create_user_duplicate_email_raises_error(db_session, test_user):
    # Arrange
    service = UserService(db_session)
    data = UserCreate(email=test_user.email, password="Pass123!")

    # Act & Assert
    with pytest.raises(DuplicateError):
        await service.create(data)
```

## Integration Tests - API Endpoints

```python
# tests/integration/api/test_users.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_user_endpoint(client: AsyncClient):
    # Arrange
    payload = {
        "email": "new@example.com",
        "password": "Pass123!"
    }

    # Act
    response = await client.post("/api/v1/users", json=payload)

    # Assert
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new@example.com"
    assert "password" not in data  # Not in response

@pytest.mark.asyncio
async def test_get_nonexistent_user_returns_404(client: AsyncClient):
    response = await client.get("/api/v1/users/999999")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
```

## Fixtures (conftest.py)

```python
import pytest
from httpx import AsyncClient
from redact_api.main import app
from redact_api.db import get_db, async_session_maker

@pytest.fixture
async def db_session():
    async with async_session_maker() as session:
        yield session
        await session.rollback()

@pytest.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
async def test_user(db_session):
    from redact_api.db.models import User
    user = User(email="test@example.com", password_hash="hashed")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user
```

## Coverage Requirements

- **Overall**: 80%+ line coverage
- **Critical paths**: 90%+ (auth, validation, core logic)
- **Happy path + error cases + edge cases**

```bash
pytest --cov=redact_api --cov-report=term-missing --cov-fail-under=80
```

## What to Test

### Must Test:
- ✅ Happy path (normal operation)
- ✅ Validation errors (422 responses)
- ✅ Not found (404 responses)
- ✅ Duplicate constraints (409 responses)
- ✅ Unauthorized (401 responses)
- ✅ Forbidden (403 responses)
- ✅ Business rule violations
- ✅ Edge cases (null, empty, boundary values)

### Don't Test:
- ❌ FastAPI framework code
- ❌ Pydantic validation (already tested)
- ❌ SQLAlchemy internals
- ❌ Third-party libraries

---

Reference parent `workspace/.claude/shared/testing-philosophy.md` for comprehensive testing guidelines.
