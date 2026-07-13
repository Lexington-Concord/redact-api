# Claude Code Configuration - Backend Template

Claude Code agents, commands, and documentation for Python FastAPI microservice development.

## What's Included

### Agents (`agents/`)

Specialized agents for Python FastAPI backend development:

- **api-designer.md** - FastAPI endpoint design, REST conventions, OpenAPI
- **backend-implementer.md** - Implements features following service layer patterns
- **security-reviewer.md** - Auth, validation, security vulnerabilities
- **test-writer.md** - Writes comprehensive pytest tests
- **database-migration-reviewer.md** - Alembic migration safety and correctness
- **async-patterns-reviewer.md** - Async/await, concurrency, session handling
- **code-reviewer.md** - Python code quality and FastAPI patterns
- **observability-reviewer.md** - Logging, metrics, tracing

### Commands (`commands/`)

Workflow automation for backend development:

- **follow-pod.md** - Stream Kubernetes pod logs for this service
- **implement.md** - Implement features following backend patterns

### Shared Documentation (`shared/`)

Backend-specific guidelines:

- **edge-cases.md** - Edge cases for FastAPI/SQLAlchemy testing
- **testing-philosophy.md** - pytest and FastAPI testing standards
- **output-formats.md** - Review output formats with backend examples

### Code Quality Guides

- **TEMPLATE-TESTING.md** - Complete testing workflow for generated projects
  - Quick verification (5 min) and comprehensive testing phases
  - Project generation, linting, type checking, testing
  - Troubleshooting guide and complete verification script
  - How to launch and test running application

- **RUFF-GUIDE.md** - Comprehensive ruff linting rules and violation fixes
  - Rule categories and enforcement strategy
  - Common violations with code examples and fixes
  - Verification workflow for generated projects
  - Patterns from template production-readiness work

## How to Use

### Running Reviews

```bash
# Quick review for small changes
/review-quick

# Standard review with selective delegation
/review-standard

# Thorough review for major changes
/review-thorough
```

### Implementing Features

```bash
# Implement a new feature
/implement "Add user profile endpoints with avatar upload"
```

### Debugging Production

```bash
# Follow pod logs
/follow-pod app=backend-api
```

## Tech Stack

This configuration is optimized for:

- **Python 3.11+**
- **FastAPI** - Web framework
- **Pydantic** - Data validation
- **SQLAlchemy 2.0** - ORM with async support
- **Alembic** - Database migrations
- **pytest** - Testing framework
- **Ruff** - Linting
- **MyPy** - Type checking

## Project Structure

```
app/
├── api/v1/endpoints/    # API route handlers
├── models/              # Pydantic schemas
├── services/            # Business logic
├── db/models/           # SQLAlchemy models
└── core/                # Config, security, etc.

tests/
├── unit/                # Service unit tests
├── integration/         # API integration tests
└── conftest.py          # Shared fixtures

alembic/                 # Database migrations
```

## Standards Enforced

### Linting & Type Checking

**Zero violations required:**

```bash
ruff check .   # Must pass
mypy .         # Must pass
pytest         # 100% pass rate
```

For complete testing workflow, see **[TEMPLATE-TESTING.md](TEMPLATE-TESTING.md)** with:
- Quick verification (5 min)
- Comprehensive testing phases
- Troubleshooting guide
- Complete verification script

### Ruff Linting

All ruff violations must be **fixed through code refactoring**, not suppressed. Consult **RUFF-GUIDE.md** for:

- Rule categories (E, F, I, ANN, UP, EM, TRY, PLR, ARG, S, etc.)
- Common patterns causing violations
- Fixes using dispatch patterns, exception restructuring, constant extraction
- Verification workflow with copier generation

**Suppressions only allowed with explicit justification:**
- `S608` - SQL injection false positives on exception messages
- `ARG002/ARG003` - Unused protocol interface parameters
- `RUF006` - Intentional fire-and-forget asyncio patterns

### Code Patterns

- **Service layer** for business logic
- **Pydantic models** for validation
- **Async/await** throughout
- **Type annotations** on all functions (including `-> None`)
- **Error messages in variables** (EM101 rule)
- **No magic numbers** (extract to constants)

## Customization

This is a template project. Customize for your needs:

1. **Update paths** - Adjust file structure if different
2. **Add domain knowledge** - Include business-specific patterns
3. **Configure agents** - Adjust agent tools/models in frontmatter
4. **Extend shared docs** - Add project-specific guidelines

## Universal Patterns

For language-agnostic patterns and Python conventions, see:

- `../workspace-template/PYTHON-PATTERNS.md` - Universal Python coding standards
- `../workspace-template/WORKSPACE-PATTERNS.md` - Workspace organization and development workflows
- `RUFF-GUIDE.md` - FastAPI template-specific ruff enforcement patterns (this directory)

## License

This is free and unencumbered software released into the public domain.

For more information, please refer to <http://unlicense.org/>
