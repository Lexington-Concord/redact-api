# Ruff Linting Guide for FastAPI Template

## Overview

This template enforces a comprehensive set of ruff linting rules to maintain production-grade code quality. All violations must be fixed **without using `noqa` suppressions** (except where explicitly documented).

**Current Status:** 0 violations in generated projects ✅

## Ruff Configuration

**File:** `pyproject.toml`
- **Line length:** 88 characters
- **Source dirs:** `redact_api`

## Rule Categories

### Core Rules (E, F)
- **E501:** Line too long
- **F401:** Unused imports
- **F821:** Undefined name

### Import Sorting (I)
- **I001:** Unsorted imports
- Group order: stdlib → third-party → local with blank lines between

### Type Annotations (ANN)
- **ANN001:** Missing type annotation for function argument
- **ANN202:** Missing return type for private function
- **ANN401:** Using `Any` type (replace with `object` or specific type)

### Python Version Updates (UP)
- **UP017:** Use `datetime.UTC` instead of `datetime.timezone.utc`
- **UP035:** Use `collections.abc.Iterator` instead of `typing.Iterator`
- **UP043:** Remove default type arguments (e.g., `AsyncGenerator[T, None]` → `AsyncGenerator[T]`)

### Error Messages (EM)
- **EM101:** String literals in exception messages must use variables
  ```python
  # ❌ WRONG
  raise ValueError("Something went wrong")

  # ✅ CORRECT
  msg = "Something went wrong"
  raise ValueError(msg)
  ```

### Exception Handling (TRY)
- **TRY003:** Avoid specifying plain `Exception` with argument
- **TRY300:** Consider moving statement to an `else` block
  - Use when return statement in try block should be in else
  ```python
  # ❌ WRONG
  try:
      result = do_something()
      return result
  except ValueError:
      return None

  # ✅ CORRECT
  try:
      result = do_something()
  except ValueError:
      return None
  else:
      return result
  ```

### Complexity (PL, C90)
- **PLR0911:** Too many return statements (max 6)
  - Fix by extracting helper functions or using dispatch pattern
  ```python
  # ✅ Use dispatch pattern for many returns
  handlers = {
      Type.A: handle_a,
      Type.B: handle_b,
      Type.C: handle_c,
  }
  handler = handlers.get(type_param)
  if handler:
      return handler()
  ```
- **PLR2004:** Magic value in comparison - extract to constant
  ```python
  # ✅ Extract constants at module top
  HTTP_201_CREATED = 201
  assert response.status_code == HTTP_201_CREATED
  ```

### Unused Arguments (ARG)
- **ARG001:** Unused function argument - prefix with `_`
- **ARG002:** Unused method argument - prefix with `_` (justifies noqa if required by protocol)
- **ARG003:** Unused class method argument - prefix with `_` (justifies noqa if required by protocol)

### Security (S)
- **S608:** Possible SQL injection (false positives on exception messages)
  - These are exception strings, not SQL queries - use `# noqa: S608`

### Other Important Rules
- **B:** flake8-bugbear (common bugs)
- **SIM:** flake8-simplify (code simplification)
- **PL:** Pylint (static analysis)
- **RUF:** Ruff-specific rules
  - **RUF006:** Store asyncio.create_task reference (use noqa for justified fire-and-forget)
- **N:** pep8-naming (naming conventions)
- **A:** Don't shadow built-ins
- **W:** pycodestyle warnings

## Common Violations & Fixes

### 1. Line Too Long (E501)
**When:** Line exceeds 88 characters

**Fixes:**
- Wrap long function signatures across multiple lines
- Wrap long docstring lines at word boundaries
- Break long import statements
- Use variables for long expressions

```python
# ❌ WRONG
def process_data(user_id: UUID, organization_id: UUID, include_details: bool = False) -> dict[str, Any]:

# ✅ CORRECT
def process_data(
    user_id: UUID,
    organization_id: UUID,
    include_details: bool = False,
) -> dict[str, Any]:
```

### 2. Unsorted Imports (I001)
**When:** Imports not in proper group order

**Fix:** Organize as:
1. Standard library imports
2. Third-party imports
3. Local application imports

```python
# ✅ CORRECT ORDER
import asyncio
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from sqlalchemy import select

from myapp.models import User
from myapp.core import config
```

### 3. Too Many Return Statements (PLR0911)
**When:** Function has >6 return statements

**Fixes:**
- Extract helper functions
- Use dispatch pattern (dict lookup)
- Restructure conditional logic

```python
# ❌ WRONG: 8 returns
async def dispatch(type_param: str):
    if type_param == "a":
        return await handle_a()
    elif type_param == "b":
        return await handle_b()
    # ... more returns

# ✅ CORRECT: Use dispatch
handlers = {
    "a": handle_a,
    "b": handle_b,
}
handler = handlers.get(type_param)
if handler:
    return await handler()
raise ValueError(f"Unknown type: {type_param}")
```

### 4. Return in Try Block (TRY300)
**When:** Return statement in try block should use else

```python
# ❌ WRONG
try:
    result = operation()
    return result
except ValueError:
    return None

# ✅ CORRECT
try:
    result = operation()
except ValueError:
    return None
else:
    return result
```

### 5. Magic Values (PLR2004)
**When:** Hardcoded numbers in comparisons

**Fix:** Extract to module-level constant

```python
# ❌ WRONG
if response.status_code == 201:
    ...

# ✅ CORRECT
HTTP_201_CREATED = 201
if response.status_code == HTTP_201_CREATED:
    ...
```

### 6. Unnecessary Type Arguments (UP043)
**When:** `AsyncGenerator[T, None]` or `Generator[T, None, None]`

**Fix:** Remove defaults

```python
# ❌ WRONG
async def gen() -> AsyncGenerator[int, None]:
    yield 1

# ✅ CORRECT
async def gen() -> AsyncGenerator[int]:
    yield 1
```

### 7. Missing Type Annotations
**When:** Function arguments or return types lack types

**Fixes:**
- Add explicit type hints to all parameters
- Add return type to all functions (use `-> None` if no return)
- For protocol methods with unused args, prefix with `_` and justify noqa

```python
# ❌ WRONG
def process(data, config):
    return result

# ✅ CORRECT
def process(data: dict[str, Any], config: Config) -> ProcessResult:
    return result

# ✅ PROTOCOL METHODS
class MyImpl(MyProtocol):
    async def callback(self, _context: Context, _request: Request) -> None:
        # noqa: ARG002 - required by protocol interface
        ...
```

## Verification Workflow

### 1. Generate Fresh Project
```bash
cd /tmp && rm -rf test_verify
copier copy /path/to/template test_verify \
  --data project_slug=test_project \
  --data "project_name=Test" \
  --defaults
```

### 2. Run Ruff Check
```bash
cd test_verify
uv run ruff check . --statistics
```

Should show: `All checks passed! ✅`

### 3. Full Verification
```bash
# Check violations
uv run ruff check .

# Type checking (note: some mypy errors are expected in generated projects)
uv run mypy . --ignore-missing-imports 2>&1 | head -20

# Tests
uv run pytest -xvs 2>&1 | head -50
```

## Files to Modify When Adding Features

### Template Source Files
- `alembic/env.py` - Database migrations
- `redact_api/api/*.py` - API endpoints
- `redact_api/core/*.py` - Business logic, middleware
- `redact_api/models/*.py` - Database models
- `redact_api/services/*.py` - Service layer
- `redact_api/tests/*.py` - Test fixtures and test cases

### Never Suppress Violations
Only use `# noqa` for:
1. **S608 (SQL injection false positives):** Exception message f-strings
2. **ARG002/ARG003 (Unused protocol args):** With justification comment
3. **RUF006 (Dangling task):** For intentional fire-and-forget with comment

## Quick Reference

| Rule | Problem | Solution |
|------|---------|----------|
| E501 | Line too long | Wrap at 88 chars |
| I001 | Unsorted imports | Reorganize groups |
| ANN001 | Missing type annotation | Add type hint |
| UP043 | Default type args | Remove defaults |
| EM101 | String in exception | Extract to variable |
| TRY300 | Return in try | Move to else block |
| PLR2004 | Magic value | Extract constant |
| PLR0911 | Too many returns | Use dispatch/helpers |
| ARG001/002 | Unused argument | Prefix with `_` |

## Resources

- **Ruff Documentation:** https://docs.astral.sh/ruff/
- **Python Patterns:** See `PYTHON-PATTERNS.md`
- **Last Commit:** `f3feba4` - Fix all remaining ruff violations

## Session Context

**Previous Session Results:** Fixed 25 violations across 8 files
- Core module refactoring (tenants.py: 3 violations)
- Test fixture improvements (conftest.py: 9 violations)
- Type annotation additions (4 files)
- Line wrapping and constants (5 files)

Use this guide to avoid the investigation work from the last session!
