---
name: test-instance
description: "[DEPRECATED] Manage FastAPI template test instance - use direct development workflow instead"
---

# Test Instance Management Skill

> **DEPRECATED**: This skill is deprecated with the runnable-first architecture.
>
> **New workflow**: Work directly on `redact_api/` in the template repository.
> No need for separate test instances.
>
> See [CLAUDE.md](../../../CLAUDE.md#development-workflow) for the current workflow.

## Why Deprecated

The fastapi-template has been converted to a **runnable-first architecture**:

- **Main branch** contains runnable Python code (`redact_api/`)
- Template variables are generated at release time via GitHub Actions
- Development happens directly on the template with instant feedback

## Old vs New Workflow

| Old (Deprecated) | New (Current) |
|------------------|---------------|
| `/test-instance generate` | Not needed - work directly on main |
| `/test-instance verify` | Run `uv run ruff check .`, `uv run mypy .`, `uv run pytest` directly |
| `/test-instance sync` | Not needed - no instances to sync |
| `/test-instance shell` | Just `cd fastapi-template` |
| `reverse-sync` | Not needed - changes are made directly to code |

## Current Development Commands

```bash
cd /home/matt/workspace/meta-work/fastapi-template

# Run tests
uv run pytest redact_api/tests/

# Linting
uv run ruff check redact_api

# Type checking
uv run mypy redact_api
```

## For Parallel Development

Use git worktrees instead of test instances:

```bash
# Create worktree for feature development
git worktree add ../fastapi-template-feature-auth feature/auth

# Work in worktree
cd ../fastapi-template-feature-auth
uv sync && uv run pytest  # Works immediately!
```

## Legacy Implementation (Do Not Use)

The script `scripts/manage-test-instance.sh` still exists but is deprecated.
It will be removed in a future version.
