# Testing Guide

This template includes a comprehensive test suite with production-grade coverage patterns. This guide explains the testing architecture and how to extend it.

## Test Architecture

### Test Infrastructure

Tests use:
- **pytest**: Test framework with asyncio support
- **pytest-docker**: Automatically spins up Postgres via docker-compose.yml
- **pytest-alembic**: Integration with Alembic for schema validation
- **httpx**: Async HTTP client for API testing
- **Real Database**: Tests use real Postgres, not SQLite mocks

### Test Fixture Setup (conftest.py)

**Key fixtures:**

- `database_url` (session): Waits for Docker Postgres, returns connection URL
- `alembic_config` (session): Configures Alembic for migrations
- `alembic_engine` (session): Sync engine for running migrations
- `engine` (session): Async SQLAlchemy engine, runs migrations
- `session_maker` (session): Factory for creating test sessions
- `reset_db` (autouse): Truncates tables before each test
- `client` (function): AsyncClient with session dependency override

**Why real database?**
- Tests database layer directly (finds N+1 queries, constraint violations)
- Validates schema matches ORM definitions
- Catches migration bugs early
- More realistic than mocked SQLite

## Test Organization

### Test Structure: AAA Pattern

All tests follow Arrange-Act-Assert with blank lines:

```python
@pytest.mark.asyncio
async def test_create_user_with_valid_data(client: AsyncClient) -> None:
    """Create user with valid data returns 201."""
    # Arrange
    payload = {"name": "Jane Doe", "email": "jane@example.com"}

    # Act
    response = await client.post("/users", json=payload)

    # Assert
    assert response.status_code == HTTPStatus.CREATED
    data = response.json()
    assert data["name"] == "Jane Doe"
```

### Test Organization by Feature

Each module has test classes organizing related tests:

**test_users.py:**
- `TestUserCRUD`: CRUD operations (create, read, update, delete)
- `TestUserOrganizationRelationship`: Relationship expansion, N+1 prevention
- `TestActivityLogging`: Audit trail recording
- `TestValidation`: Input validation (email format, length limits)

**test_organizations.py:**
- `TestOrganizationCRUD`: Create, read, update, delete
- `TestOrganizationUserRelationship`: Related users expansion
- `TestActivityLogging`: Audit trail

**test_memberships.py:**
- `TestMembershipCRUD`: Create, read, delete
- `TestMembershipConstraints`: Uniqueness, foreign key validation
- `TestCascadeDelete`: Deleting users/orgs cascades to memberships

**test_documents.py:**
- `TestDocumentUpload`: File upload with size validation
- `TestDocumentDownload`: File download and streaming
- `TestValidation`: Filename, content-type requirements

**test_health.py:**
- `TestHealth`: Database connectivity checks
- `TestPing`: Liveness probe

**test_migrations.py:**
- `TestMigrations`: Upgrade/downgrade cycles
- `TestSchemaDrift`: ORM models match database schema

## Test Coverage Categories

### 1. Happy Path Tests

Normal operation, valid inputs:

```python
async def test_create_user_success(client: AsyncClient) -> None:
    """Create user with valid data returns 201."""
    response = await client.post("/users", json={...})
    assert response.status_code == HTTPStatus.CREATED
    # Validate response structure
```

### 2. Validation Error Tests

Invalid inputs, expected 422 responses:

```python
async def test_create_user_invalid_email(client: AsyncClient) -> None:
    """Create user with invalid email returns 422."""
    response = await client.post("/users", json={
        "name": "Jane",
        "email": "not-an-email"  # Invalid
    })
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    # Validate error detail mentions email
```

### 3. Not Found Tests

Resource not found, expected 404 responses:

```python
async def test_get_user_not_found(client: AsyncClient) -> None:
    """Get non-existent user returns 404."""
    response = await client.get(f"/users/{uuid4()}")
    assert response.status_code == HTTPStatus.NOT_FOUND
```

### 4. Constraint Tests

Database constraints enforced:

```python
async def test_create_duplicate_membership(client: AsyncClient) -> None:
    """Creating duplicate membership violates unique constraint."""
    # Create user and org
    # Create membership (succeeds)
    # Try duplicate (fails with 400 or constraint error)
```

### 5. Relationship Tests

Related data properly expanded:

```python
async def test_user_read_includes_organizations(client: AsyncClient) -> None:
    """User response includes related organizations."""
    # Create user, org, membership
    # Get user
    # Assert organizations list populated
```

### 6. N+1 Prevention Tests

List endpoints don't have N+1 query problems:

```python
async def test_list_users_includes_organizations_efficiently(client: AsyncClient) -> None:
    """List users response includes organizations (batch loaded)."""
    # Create multiple users with organizations
    # List users
    # Assert all organizations populated (via batch loading, not N queries)
```

### 7. Cascade Tests

Foreign key cascades work correctly:

```python
async def test_delete_user_cascades_to_memberships(client: AsyncClient) -> None:
    """Deleting user cascades delete to memberships."""
    # Create user with memberships
    # Delete user
    # Assert memberships also deleted
```

### 8. Pagination Tests

Pagination parameters respected:

```python
async def test_list_users_respects_page_size(client: AsyncClient) -> None:
    """List respects pagination_page_size_max setting."""
    # Create 5 users
    # Request with size=1000 (over max)
    # Assert 422 validation error
```

## Running Tests

### Run all tests
```bash
uv run pytest
```

### Run specific file
```bash
uv run pytest redact_api/tests/test_users.py
```

### Run specific test
```bash
uv run pytest redact_api/tests/test_users.py::TestUserCRUD::test_create_user_success
```

### Run with coverage
```bash
uv run pytest --cov=redact_api --cov-report=html
```

### Run specific test class
```bash
uv run pytest redact_api/tests/test_users.py::TestUserCRUD
```

### Watch mode (requires pytest-watch)
```bash
uv run pytest-watch redact_api/tests/
```

## Coverage Expectations

### Minimum Coverage Targets
- **Overall**: 80% line coverage
- **API endpoints**: 80% (every endpoint tested for happy path + common errors)
- **Business logic**: 85% (all paths, edge cases)
- **Critical operations**: 90% (auth, payments, data validation)

### What's OK to Skip
- Framework code (FastAPI decorators, Pydantic internals)
- Third-party library code
- Configuration files
- Database migrations (tested via pytest-alembic)
- Development-only scripts

### Coverage Report
```bash
uv run pytest --cov=redact_api --cov-report=term-missing
# Shows which lines aren't covered
```

## Adding New Tests

When adding a new endpoint:

1. **Create test in appropriate file** (test_<resource>.py)
2. **Add test class** if needed (TestNewResource)
3. **Write tests for:**
   - Happy path (201/200 success)
   - Validation errors (422)
   - Not found (404)
   - Constraints (400)
   - Edge cases (empty input, very long strings, etc.)
4. **Use fixtures** for shared setup
5. **Follow AAA pattern** with blank lines between sections
6. **Use HTTPStatus enums** for status codes
7. **Validate response structure** (not just status code)

### Test Template

```python
@pytest.mark.asyncio
async def test_endpoint_behavior(client: AsyncClient) -> None:
    """Brief description of what is tested and expected result."""
    # Arrange - set up data
    payload = {...}

    # Act - make the request
    response = await client.post("/endpoint", json=payload)

    # Assert - verify result
    assert response.status_code == HTTPStatus.CREATED
    data = response.json()
    assert data["field"] == expected_value
```

## Debugging Test Failures

### See detailed output
```bash
uv run pytest -vv redact_api/tests/test_file.py::test_name
```

### Print debug info
```python
async def test_something(client: AsyncClient) -> None:
    response = await client.post(...)
    print(f"Status: {response.status_code}")
    print(f"Body: {response.json()}")
    assert ...
```

### Run with database echo
```bash
SQLALCHEMY_ECHO=true uv run pytest redact_api/tests/test_users.py
```

### Check database state during test
```python
async def test_something(session_maker: async_sessionmaker) -> None:
    # ... test code ...
    # Check database state
    async with session_maker() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        print(f"Users in DB: {users}")
```

## Common Test Patterns

### Testing with relationships
```python
async def test_user_with_organizations(client: AsyncClient) -> None:
    # Create user
    user = await client.post("/users", json={...}).json()
    # Create org
    org = await client.post("/organizations", json={...}).json()
    # Create membership
    await client.post("/memberships", json={
        "user_id": user["id"],
        "organization_id": org["id"]
    })
    # Get user - should include organizations
    response = await client.get(f"/users/{user['id']}")
    assert len(response.json()["organizations"]) == 1
```

### Testing error scenarios
```python
async def test_create_with_missing_field(client: AsyncClient) -> None:
    response = await client.post("/users", json={
        "name": "Jane"  # Missing email
    })
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    error = response.json()
    assert "email" in error["detail"][0]["loc"]
```

### Testing cascade deletes
```python
async def test_cascade_deletes_memberships(client: AsyncClient) -> None:
    # Create related data
    user_id = (await client.post("/users", json={...})).json()["id"]
    org_id = (await client.post("/organizations", json={...})).json()["id"]
    await client.post("/memberships", json={...})

    # Delete user
    await client.delete(f"/users/{user_id}")

    # Verify memberships deleted (by trying to find them)
    # This depends on whether you expose a list endpoint for memberships
```

## Performance Testing Patterns

While not included in basic test suite, here's how to add performance tests:

```python
import time

@pytest.mark.asyncio
async def test_list_users_performance(client: AsyncClient) -> None:
    """List users should complete in <100ms with 100 items."""
    # Create 100 users
    for i in range(100):
        await client.post("/users", json={
            "name": f"User {i}",
            "email": f"user{i}@example.com"
        })

    # Time the list operation
    start = time.time()
    response = await client.get("/users?size=100")
    elapsed = time.time() - start

    # Should be fast
    assert elapsed < 0.1  # 100ms
    assert response.status_code == HTTPStatus.OK
    assert response.json()["total"] == 100
```

## CI/CD Integration

When running in CI/CD:

```bash
# Run all checks
uv run ruff check .
uv run mypy redact_api
uv run pytest --cov=redact_api

# Generate coverage report
uv run pytest --cov=redact_api --cov-report=xml  # For CI upload
```

Tests should:
- Pass with zero failures
- Have 80%+ coverage
- Complete in <60 seconds
- Work in parallel (pytest -n auto)

## Further Reading

- [pytest documentation](https://docs.pytest.org/)
- [httpx async client](https://www.python-httpx.org/)
- [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio)
- [sqlalchemy async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
