# FastAPI Template Testing Guide

Complete testing workflow for verifying generated template instances are production-ready.

---

## Quick Verification (5 minutes)

For quick validation after template changes:

```bash
# 1. Generate fresh project
cd /tmp && rm -rf test_template
copier copy /path/to/fastapi-template test_template \
  --data project_slug=myproject \
  --data "project_name=My Project" \
  --defaults

# 2. Run all checks
cd test_template
uv run ruff check .
uv run mypy . --ignore-missing-imports
uv run pytest tests/ -q
```

Expected results:
- ✅ `ruff check`: All checks passed!
- ✅ `mypy`: No errors
- ✅ `pytest`: All tests pass

---

## Comprehensive Testing Workflow

### Phase 1: Project Generation

```bash
# Create temporary directory
cd /tmp && rm -rf test_redact_api
mkdir -p test_redact_api

# Generate from template using copier
copier copy /path/to/fastapi-template test_redact_api \
  --data project_slug=test_project \
  --data "project_name=Test Project" \
  --defaults

# Verify project structure
cd test_redact_api
ls -la
```

**What this does:**
- Generates a concrete project instance from the template
- Replaces all `redact_api` and `redact-api` variables
- Creates complete file structure with all dependencies

**Expected output:**
```
├── alembic/                    # Database migrations
├── test_project/               # Main package
│   ├── api/                    # API endpoints
│   ├── core/                   # Config, auth, storage
│   ├── db/                     # Database session, models
│   ├── models/                 # Pydantic schemas
│   ├── services/               # Business logic
│   ├── main.py                 # FastAPI app
│   └── tests/                  # Test suite
├── pyproject.toml              # Dependencies
├── .env.example                # Environment template
└── .claude/                    # Claude Code configuration
```

---

### Phase 2: Environment Setup

```bash
# Install dependencies via uv
cd test_redact_api
uv sync

# Verify uv installation
uv --version
```

**Expected output:**
- ✅ Dependencies installed to `.venv`
- ✅ No errors or warnings about conflicting dependencies

**If installation fails:**
- Check `pyproject.toml` for syntax errors
- Verify Python 3.11+ is available: `python --version`
- Clear cache: `rm -rf .venv && uv sync`

---

### Phase 3: Linting (Ruff)

```bash
# Run ruff check with statistics
uv run ruff check . --statistics

# Or just verify pass/fail
uv run ruff check .
```

**Expected output:**
```
All checks passed! ✅
```

**If violations found:**
- See [RUFF-GUIDE.md](RUFF-GUIDE.md) for violations and fixes
- Common violations:
  - **E501**: Line too long → Wrap at 88 characters
  - **I001**: Unsorted imports → Reorganize import groups
  - **ANN001**: Missing type annotation → Add type hints
  - **PLR0911**: Too many returns → Extract helper functions

**Suppress output by rule (for review):**
```bash
# Count violations by rule
uv run ruff check . --select E501 --statistics

# Check specific file
uv run ruff check test_project/api/users.py
```

---

### Phase 4: Type Checking (MyPy)

```bash
# Run mypy with lenient settings (some errors expected in generated projects)
uv run mypy . --ignore-missing-imports

# Stricter check
uv run mypy . --ignore-missing-imports --warn-unused-configs
```

**Expected output:**
```
Success: no issues found in X source files
```

**If type errors found:**
- Check specific files: `uv run mypy test_project/api/`
- Add missing type annotations
- Fix incompatible types

**Common issues:**
- Missing return type on async functions → Add `-> None` or return type
- Implicit `Any` types → Replace with specific types or `object`
- SQLAlchemy type confusion → Use `cast()` or fix column type definitions

---

### Phase 5: Testing (Pytest)

```bash
# Run tests with Docker dependencies
uv run pytest tests/ -v

# Run specific test
uv run pytest tests/test_users.py -v

# Run with coverage
uv run pytest tests/ --cov=test_project --cov-report=html
```

**Prerequisites:**
- Docker running for Postgres test database
- `.env` file with `DATABASE_URL` pointing to test DB

**Expected output:**
```
tests/test_api_users.py::test_create_user PASSED         [ 10%]
tests/test_api_users.py::test_get_user PASSED            [ 20%]
tests/test_api_organizations.py::test_create_org PASSED  [ 30%]
...
========== X passed in Y.XXs ==========
```

**If tests fail:**
- Check Docker: `docker ps` should show postgres container
- Check database: `docker logs postgres_container_name`
- Run specific test with `-vv` for debugging: `uv run pytest tests/test_users.py::test_create_user -vv`

**Common issues:**
- **Database connection failed** → Start Docker, ensure `DATABASE_URL` is set
- **Migration errors** → Check `alembic/versions/` for valid migrations
- **Import errors** → Verify package structure, check `__init__.py` files
- **Async errors** → Use `@pytest.mark.asyncio` on async test functions

---

### Phase 6: Application Launch

```bash
# Set environment variables
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db"
export SECRET_KEY="dev-key-change-in-production"

# Run development server
uv run fastapi dev test_project/main.py

# Or with uvicorn directly
uv run uvicorn test_project.main:app --reload
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

**Test endpoints:**
```bash
# Get OpenAPI documentation
curl http://localhost:8000/docs

# Create user
curl -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -d '{"name": "Test User", "email": "test@example.com"}'

# Get users
curl http://localhost:8000/users
```

---

## Complete Verification (Recommended)

Use the persistent test instance for faster verification without repeated approvals:

```bash
# First time setup
/test-instance generate

# After template changes
/test-instance sync     # Pull template changes
/test-instance verify   # Run ruff, mypy, pytest
```

**Why prefer persistent instance?**
- Faster (no repeated generation)
- No user approval needed for verification
- Git-tracked for copier update
- Reusable across sessions

### Alternative: One-Off Temporary Verification

For quick testing of one-time variations, the original temporary workflow still works:

```bash
#!/bin/bash
set -e

TEMPLATE_PATH="/path/to/fastapi-template"
TEST_DIR="/tmp/test_redact_api_$(date +%s)"

echo "📦 Generating template instance..."
mkdir -p "$TEST_DIR"
copier copy "$TEMPLATE_PATH" "$TEST_DIR" \
  --data project_slug=test_project \
  --data "project_name=Test Project" \
  --defaults

cd "$TEST_DIR"

echo "📚 Installing dependencies..."
uv sync

echo "🔍 Running ruff check..."
if ! uv run ruff check . --statistics; then
  echo "❌ Ruff violations found"
  exit 1
fi

echo "🔎 Running mypy..."
if ! uv run mypy . --ignore-missing-imports; then
  echo "❌ Type errors found"
  exit 1
fi

echo "🧪 Running pytest..."
if ! uv run pytest tests/ -q; then
  echo "❌ Tests failed"
  exit 1
fi

echo "✅ All checks passed!"
echo "Template location: $TEST_DIR"
```

Save as `verify-template.sh`, make executable, and run:

```bash
chmod +x verify-template.sh
./verify-template.sh
```

---

## Troubleshooting

### "copier copy" fails

**Problem:** `ModuleNotFoundError: No module named 'copier'`

**Solution:**
```bash
pip install copier>=9.0.0
```

### Ruff violations in generated project

**Problem:** Generated project has ruff violations

**Solution:**
1. Fix violations in template source files
2. See [RUFF-GUIDE.md](RUFF-GUIDE.md) for violation patterns
3. Regenerate project and verify

### MyPy errors

**Problem:** Type checking failures in generated code

**Solution:**
1. Add type annotations to function parameters and returns
2. Use `cast()` for SQLAlchemy type mismatches
3. Check for missing `-> None` on functions without return values

### Pytest fails with database error

**Problem:** `Can't connect to postgresql://localhost/test_db`

**Solution:**
1. Ensure Docker is running: `docker ps`
2. Check database container: `docker logs postgres`
3. Update `.env` file with correct `DATABASE_URL`
4. Run migrations: `uv run alembic upgrade head`

### Port 8000 already in use

**Problem:** `[Errno 98] Address already in use`

**Solution:**
```bash
# Use different port
uv run fastapi dev test_project/main.py --port 8001

# Or kill process using port
lsof -i :8000
kill -9 <PID>
```

---

## Files to Modify When Fixing Template Issues

When fixing template source files to improve the generated project:

**Template source files:**
- `alembic/env.py` - Database migrations
- `redact_api/api/*.py` - API endpoints
- `redact_api/core/*.py` - Config, auth, storage
- `redact_api/models/*.py` - Pydantic schemas
- `redact_api/services/*.py` - Business logic
- `redact_api/tests/*.py` - Test fixtures
- `pyproject.toml` - Dependencies and configuration

**Template configuration:**
- `copier.yml` - Template parameters
- `_templates/` - Jinja2 template files
- `.claude/` - Claude Code configuration

---

## Related Documentation

- **[RUFF-GUIDE.md](RUFF-GUIDE.md)** - Linting rules and violation fixes
- **[README.md](README.md)** - Configuration and agents
- **[shared/testing-philosophy.md](shared/testing-philosophy.md)** - Pytest patterns
- **[shared/edge-cases.md](shared/edge-cases.md)** - FastAPI/SQLAlchemy edge cases
- **[../workspace-template/PYTHON-PATTERNS.md](../workspace-template/PYTHON-PATTERNS.md)** - Python conventions

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `copier copy ...` | Generate new project from template |
| `uv sync` | Install dependencies |
| `uv run ruff check .` | Lint violations |
| `uv run mypy .` | Type checking |
| `uv run pytest tests/` | Run test suite |
| `uv run fastapi dev` | Start dev server |
| `uv run alembic upgrade head` | Apply migrations |

---

## Current Template Status

**Last verified:** 2026-01-06

Generated projects have:
- ✅ **0 ruff violations** - All linting rules enforced
- ✅ **0 type errors** - Full type coverage
- ✅ **100% test pass rate** - All integration tests passing
- ✅ **Production-ready** - Async, multi-tenant, cloud storage support

See commit `f3feba4` for latest fixes.
