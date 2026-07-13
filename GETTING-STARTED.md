# Getting Started with FastAPI Template

Create a new FastAPI microservice from this template using Copier.

## Prerequisites

Install these tools before starting:

```bash
# Copier - template engine
pip install copier
# or
uv tool install copier

# uv - Python package manager (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Optional: DevSpace for Kubernetes development
curl -s https://raw.githubusercontent.com/loft-sh/devspace/main/install.sh | bash
```

## Quick Start

### Create a New Project

```bash
# From GitHub (recommended)
copier copy gh:mattwwarren/fastapi-template --vcs-ref copier my-new-service

# Or with explicit options
copier copy gh:mattwwarren/fastapi-template --vcs-ref copier my-new-service \
  --data project_name="My API Service" \
  --data port=8001 \
  --data auth_enabled=true \
  --data auth_provider=ory
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `project_name` | string | (required) | Human-readable project name |
| `project_slug` | string | (auto) | Python package name (auto-generated from project_name) |
| `description` | string | "A FastAPI microservice" | Brief project description |
| `port` | int | 8000 | Development server port |
| `auth_enabled` | bool | false | Enable authentication middleware |
| `auth_provider` | string | none | Auth provider: none, ory, auth0, keycloak, cognito |
| `multi_tenant` | bool | true | Enable multi-tenant isolation |
| `storage_provider` | string | local | Storage: local, s3, azure, gcs |
| `cors_origins` | string | "http://localhost:3000" | CORS allowed origins |
| `enable_metrics` | bool | true | Enable Prometheus metrics at /metrics |
| `enable_activity_logging` | bool | true | Enable audit trail logging |

### Post-Generation Steps

After Copier generates your project:

```bash
cd my-new-service

# 1. Configure environment
cp dotenv.example .env
# Edit .env - set DATABASE_URL

# 2. Install dependencies (if not done automatically)
uv sync

# 3. Install pre-commit hooks (if not done automatically)
pre-commit install

# 4. Start development server
uv run fastapi dev my_new_service/main.py
```

## Development Workflow

### Option A: Local Development (No Kubernetes)

```bash
# Start PostgreSQL (via Docker)
docker run -d --name postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  postgres:16

# Create database
docker exec postgres createdb my_new_service

# Run migrations
uv run alembic upgrade head

# Start server
uv run fastapi dev my_new_service/main.py

# Visit http://localhost:8000/docs
```

### Option B: DevSpace Development (Kubernetes)

```bash
# Start local k3d cluster (if not running)
./scripts/k3d-up.sh

# Start development environment
devspace dev

# In another terminal, create database
kubectl exec -it postgres -- createdb my_new_service

# Run migrations
devspace run alembic-upgrade
```

### Running Tests

```bash
# Run all tests (uses pytest-docker for PostgreSQL)
uv run pytest

# Run with coverage
uv run pytest --cov=my_new_service --cov-report=term-missing

# Run specific test file
uv run pytest my_new_service/tests/integration/test_health.py
```

### Code Quality

```bash
# Linting
uv run ruff check .
uv run ruff check . --fix  # Auto-fix issues

# Formatting
uv run ruff format .

# Type checking
uv run mypy .

# All checks (via pre-commit)
pre-commit run --all-files
```

## Updating from Template

When the template receives improvements, update your project:

```bash
cd my-new-service

# Preview changes
copier update --pretend

# Apply updates (interactive merge)
copier update

# Review and resolve any conflicts
git diff
git add -A && git commit -m "chore: update from template"
```

## Project Structure

```
my-new-service/
├── my_new_service/           # Python package
│   ├── api/                  # API endpoints
│   │   ├── health.py         # Health check endpoint
│   │   ├── users.py          # User endpoints
│   │   └── routes.py         # Router aggregation
│   ├── core/                 # Core utilities
│   │   ├── config.py         # Settings via pydantic-settings
│   │   ├── auth.py           # Authentication
│   │   └── middleware.py     # Request middleware
│   ├── db/                   # Database
│   │   ├── session.py        # Async session management
│   │   └── base.py           # SQLAlchemy base
│   ├── models/               # SQLAlchemy models
│   ├── services/             # Business logic layer
│   └── main.py               # FastAPI application
├── alembic/                  # Database migrations
├── tests/                    # Test suite
├── k8s/                      # Kubernetes manifests
├── .github/workflows/        # CI/CD
├── devspace.yaml             # DevSpace configuration
├── pyproject.toml            # Python dependencies
└── Dockerfile                # Production container
```

## Key Patterns

### Service Layer

Business logic lives in `services/`, not in API endpoints:

```python
# services/user_service.py
class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(self, data: UserCreate) -> User:
        # Business logic here
        ...

# api/users.py
@router.post("/users")
async def create_user(
    data: UserCreate,
    session: AsyncSession = Depends(get_session),
):
    service = UserService(session)
    return await service.create_user(data)
```

### Configuration

Settings are loaded from environment variables via pydantic-settings:

```python
# core/config.py
class Settings(BaseSettings):
    database_url: str
    debug: bool = False

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
```

### Database Sessions

Use the async session dependency:

```python
from my_new_service.db.session import get_session

@router.get("/items")
async def list_items(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Item))
    return result.scalars().all()
```

## Troubleshooting

### "Database does not exist"

```bash
# Local Docker
docker exec postgres createdb my_new_service

# DevSpace/Kubernetes
kubectl exec -it postgres -- createdb my_new_service
```

### "Alembic migration failed"

```bash
# Check current migration state
uv run alembic current

# If needed, stamp to a known state
uv run alembic stamp head

# Then run migrations
uv run alembic upgrade head
```

### "Pre-commit hooks failing"

```bash
# Update hooks
pre-commit autoupdate

# Run manually to see errors
pre-commit run --all-files
```

## Next Steps

- Review [CONFIGURATION-GUIDE.md](CONFIGURATION-GUIDE.md) for advanced configuration
- Check [docs/TENANT_ISOLATION.md](docs/TENANT_ISOLATION.md) if using multi-tenant mode
- See [TESTING_GUIDE.md](TESTING_GUIDE.md) for testing best practices

## License

This is free and unencumbered software released into the public domain.
