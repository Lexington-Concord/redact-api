# Quick Start Guide

Welcome! This is a production-ready FastAPI template with a runnable-first architecture.

## Prerequisites

- Python 3.11+
- Docker (for PostgreSQL)
- `uv` package manager (https://docs.astral.sh/uv/)

## Quick Start (2 minutes)

### 1. Install Dependencies

```bash
uv sync --dev
```

### 2. Configure Environment

```bash
# Copy environment template
cp dotenv.example .env

# Edit .env and update database connection:
DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app
```

### 3. Start Database

```bash
docker run -d \
  -e POSTGRES_USER=app \
  -e POSTGRES_PASSWORD=app \
  -e POSTGRES_DB=app \
  -p 5432:5432 \
  --name postgres \
  postgres:15
```

### 4. Run Database Migrations

```bash
uv run alembic upgrade head
```

### 5. Start Development Server

```bash
uv run fastapi dev redact_api/main.py
# Opens http://localhost:8000
# API docs: http://localhost:8000/docs
```

Verify the server is running by visiting http://localhost:8000/health in your browser.

---

## Configuration Options

All configuration is done via environment variables in `.env`. See [dotenv.example](dotenv.example) for the full list.

### Authentication

**Default**: Disabled (public API mode)

To enable authentication:
1. Set `AUTH_PROVIDER_TYPE` to your provider (ory, auth0, keycloak, cognito)
2. Configure `AUTH_PROVIDER_URL`, `AUTH_PROVIDER_ISSUER`, `JWT_PUBLIC_KEY`
3. Uncomment AuthMiddleware in `redact_api/main.py`

**Available Providers**: ory, auth0, keycloak, cognito

For provider-specific setup, see [CONFIGURATION-GUIDE.md](CONFIGURATION-GUIDE.md#authentication)

**Test endpoints without authentication**:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/ping
curl http://localhost:8000/docs
```

---

### Multi-Tenant Isolation

**Default**: Enabled (`ENFORCE_TENANT_ISOLATION=true`)

**What this does**:
- Prevents User A from accessing Organization B's data
- Enforces tenant context from JWT claims
- Applies WHERE clauses to all database queries
- Protects documents, users, memberships, and custom data

**Note**: Multi-tenant isolation requires authentication to be enabled for full functionality.

For details, see [docs/TENANT_ISOLATION.md](docs/TENANT_ISOLATION.md)

---

### Storage Provider

**Default**: Local storage (`STORAGE_PROVIDER=local`)

**Available Options**:

| Provider | Config | Requirements |
|----------|--------|--------------|
| Local | `STORAGE_PROVIDER=local` | None (development only) |
| AWS S3 | `STORAGE_PROVIDER=s3` | `pip install .[aws]` |
| Azure Blob | `STORAGE_PROVIDER=azure` | `pip install .[azure]` |
| Google Cloud | `STORAGE_PROVIDER=gcs` | `pip install .[gcs]` |

**Note**: Local storage is suitable for development. For production, use cloud storage (S3, Azure, GCS).

For setup guides, see [CONFIGURATION-GUIDE.md](CONFIGURATION-GUIDE.md#storage)

---

### Activity Logging

**Default**: Enabled (`ACTIVITY_LOGGING_ENABLED=true`)

All create, read, update, and delete operations are logged with:
- Timestamp
- User ID and email
- Action type (CREATE, READ, UPDATE, DELETE)
- Resource type and ID
- Changes made (for UPDATE)

---

### Metrics (Prometheus)

**Default**: Enabled (`ENABLE_METRICS=true`)

**Access**: http://localhost:8000/metrics

Metrics include:
- User operations (users_created_total, users_updated_total)
- Organization operations (organizations_created_total)
- Document uploads (documents_uploaded_total)
- Database query duration
- HTTP request latency

---

## Running Tests

```bash
# Run all tests
uv run pytest redact_api/tests/ -v

# Run specific test file
uv run pytest redact_api/tests/test_users.py -v

# Run specific test
uv run pytest redact_api/tests/test_users.py::TestUserCRUD::test_create_user_success -v

# Run with coverage report
uv run pytest redact_api/tests/ --cov=redact_api --cov-report=html
```

After running tests, open `htmlcov/index.html` to view coverage report.

---

## Code Quality

Verify your code meets production standards before committing:

```bash
# Lint violations
uv run ruff check redact_api

# Type checking
uv run mypy redact_api

# Run tests
uv run pytest redact_api/tests/
```

All three must pass before pushing to repository.

---

## Next Steps

1. **Read the Architecture**: [docs/architecture.rst](docs/architecture.rst) explains the project structure
2. **Add Your First Endpoint**: Follow [docs/howto_add_feature.rst](docs/howto_add_feature.rst)
3. **Configure Features**: See [CONFIGURATION-GUIDE.md](CONFIGURATION-GUIDE.md) for detailed options
4. **Review Security**: See [docs/TENANT_ISOLATION.md](docs/TENANT_ISOLATION.md) if using multi-tenant

---

## Troubleshooting

### "Can't connect to PostgreSQL"

**Problem**: `psycopg.OperationalError: connection failed`

**Solution**:
1. Ensure Docker is running: `docker ps`
2. Check DATABASE_URL in `.env` matches your setup
3. Create a test database container:
   ```bash
   docker run -d \
     -e POSTGRES_PASSWORD=postgres \
     -e POSTGRES_DB=myapp \
     -p 5432:5432 \
     --name postgres \
     postgres:15
   ```
4. Update `.env`:
   ```bash
   DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/myapp
   ```

### "Port 8000 already in use"

**Problem**: `[Errno 98] Address already in use`

**Solution**:
```bash
# Use a different port
uv run fastapi dev redact_api/main.py --port 8001

# Or kill the process using port 8000
lsof -i :8000 | grep LISTEN | awk '{print $2}' | xargs kill -9
```

### "ruff check fails"

**Problem**: Linting violations found

**Solution**:
```bash
# Auto-fix most violations
uv run ruff check --fix

# View remaining violations
uv run ruff check .

# See specific rule: .claude/RUFF-GUIDE.md
```

### "mypy reports type errors"

**Problem**: Type checking failures

**Solution**:
1. Check for missing type annotations on function parameters
2. Ensure all functions have return types (including `-> None`)
3. See type checking guide: [.claude/README.md](.claude/README.md)

### "Tests fail with 'No module named...'"

**Problem**: Import errors in tests

**Solution**:
```bash
# Reinstall with dependencies
uv sync --dev

# Verify Python path
uv run python -c "import redact_api"

# Check package structure
ls -la redact_api/
```

---

## Production Deployment Checklist

Before deploying to production, verify all items:

- [ ] Set `DEBUG=false` in `.env`
- [ ] Set `SECRET_KEY` to a random 32+ character value (don't commit to git)
- [ ] Enable authentication: uncomment AuthMiddleware
- [ ] Enable tenant isolation if using multi-tenant: uncomment TenantIsolationMiddleware
- [ ] Configure external PostgreSQL database (not local)
- [ ] Configure external storage (S3, Azure, GCS - not local filesystem)
- [ ] Set up SSL/TLS (use nginx reverse proxy)
- [ ] Configure logging level (info for production)
- [ ] Set up monitoring and alerting
- [ ] Run full test suite: `uv run pytest redact_api/tests/`
- [ ] Run security checks: `uv run ruff check . && uv run mypy .`
- [ ] Review API documentation at /docs endpoint
- [ ] Test all enabled features in staging environment

---

## Additional Resources

- **Configuration Reference**: [CONFIGURATION-GUIDE.md](CONFIGURATION-GUIDE.md)
- **Tenant Isolation Details**: [docs/TENANT_ISOLATION.md](docs/TENANT_ISOLATION.md)
- **Activity Logging**: [docs/activity_logging.md](docs/activity_logging.md)
- **Deployment Guide**: [docs/deployment.md](docs/deployment.md)
- **Testing Patterns**: [.claude/TEMPLATE-TESTING.md](.claude/TEMPLATE-TESTING.md)
- **Contributing**: See [CONTRIBUTING.md](CONTRIBUTING.md) if developing on this template

---

## Getting Help

If you encounter issues:

1. Check this Quick Start guide first
2. See [CONFIGURATION-GUIDE.md](CONFIGURATION-GUIDE.md) for detailed setup
3. Check [docs/troubleshooting.rst](docs/troubleshooting.rst)
4. Review [.claude/README.md](.claude/README.md) for Claude Code integration
5. Check recent git commit messages: `git log --oneline -20`

---

## Background Tasks: Implementation Required

This template includes **placeholder background tasks** that require implementation before production use.

### Placeholder Functions

The following background tasks are **stubs** and do not perform actual operations:

1. **Email Service** (`redact_api/core/background_tasks.py:send_welcome_email_task`)
   - **Current**: Logs "welcome_email_sent" but doesn't send emails
   - **Action Required**: Implement email integration
   - **Guide**: [docs/implementing_email_service.md](docs/implementing_email_service.md)

2. **Log Archival** (`redact_api/core/background_tasks.py:archive_old_activity_logs_task`)
   - **Current**: Logs "activity_logs_archived" but doesn't archive anything
   - **Action Required**: Implement archival strategy
   - **Guide**: [docs/implementing_log_archival.md](docs/implementing_log_archival.md)

3. **Report Generation** (`redact_api/core/background_tasks.py:generate_activity_report_task`)
   - **Current**: Logs "activity_report_generated" but doesn't generate reports
   - **Action Required**: Implement report generation and delivery
   - **Guide**: [docs/implementing_reports.md](docs/implementing_reports.md)

### HTTP Client Examples

The file `redact_api/core/http_client.py` contains **commented example patterns** (lines 61-253):
- These are reference implementations, not production code
- Uncomment and adapt when integrating with external services
- See [docs/service_integration_patterns.md](docs/service_integration_patterns.md) for integration guides

### Before Production Deployment

**Verify all placeholder implementations are replaced or removed:**

```bash
# Search for placeholder markers
grep -r "asyncio.sleep(0.1)" redact_api/

# If this returns results, you have unimplemented features
```

---

## What's Next?

Your FastAPI application is ready. Start building!

1. Create your first endpoint in `redact_api/api/`
2. Add your data models in `redact_api/models/`
3. Implement business logic in `redact_api/services/`
4. Write tests in `redact_api/tests/`
5. Deploy with confidence knowing tests pass and code is clean
