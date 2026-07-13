# FastAPI Template Deployment Guide

Documentation for deploying projects from the fastapi-template using the runnable-first workflow.

## Overview: Runnable-First Template

This template uses a **runnable-first** architecture:

- **Main branch** contains runnable Python code (`redact_api/`)
- **`copier` branch** contains the Copier template (auto-generated on release)
- Template variables (`redact_api`) are generated at release time via GitHub Actions

This approach provides several benefits:
- Developers can work directly on main branch with full IDE support
- No need to generate test instances during development
- CI/CD runs against real Python code
- Template generation is automated and consistent

---

## Deployment Workflow

### For External Users (Recommended)

Generate a new project directly from the latest release:

```bash
# Create a new service from the template
copier copy gh:mattwwarren/fastapi-template --vcs-ref copier my-service

# Answer the prompts for project configuration
# Project name, auth settings, storage provider, etc.

# Navigate to your new project
cd my-service

# Install dependencies
uv sync

# Run initial verification
uv run ruff check .
uv run mypy .
uv run pytest
```

**Note**: The `--vcs-ref copier` flag ensures you're using the templatized version, not the runnable main branch.

### For Local Testing (Contributors)

If you're contributing to the template and want to test generation locally:

```bash
# Step 1: Generate the template from runnable code
cd /path/to/fastapi-template
./scripts/templatize.sh

# Step 2: Generate a test project from the local template
copier copy .templatized/ /path/to/test-project --trust

# Step 3: Verify the generated project
cd /path/to/test-project
uv sync
uv run ruff check .
uv run mypy .
uv run pytest
```

---

## What Changed from Previous Workflow

### Old Workflow (Deprecated)

Previously, the template used a "template-first" approach:
- Main branch contained Copier template with `redact_api` variables
- Development required creating test instances
- The `manage-test-instance.sh` script managed instance lifecycle
- Changes required template-instance sync workflows

### New Workflow (Current)

The runnable-first approach:
- Main branch contains working Python code (`redact_api/`)
- Template is auto-generated from code at release time
- No test instances needed during development
- GitHub Actions creates the `copier` branch automatically

### Migration for Existing Workflows

If you were using `manage-test-instance.sh` for development:

| Old Command | New Approach |
|-------------|--------------|
| `/test-instance generate` | Not needed - work directly on main |
| `/test-instance verify` | Run `uv run ruff check .`, `uv run mypy .`, `uv run pytest` directly |
| `/test-instance sync` | Not needed - no instances to sync |
| `reverse-sync` | Not needed - changes are made directly to code |

---

## For Contributors

### Development Workflow

1. **Clone the repository**
   ```bash
   git clone https://github.com/mattwwarren/fastapi-template.git
   cd fastapi-template
   ```

2. **Work directly on main branch**
   ```bash
   # Make your changes to redact_api/
   vim redact_api/services/user_service.py

   # Run verification
   uv run ruff check .
   uv run mypy .
   uv run pytest
   ```

3. **Use git worktrees for parallel development** (optional)
   ```bash
   # Create a worktree for a feature branch
   git worktree add ../fastapi-template-feature feature-branch
   cd ../fastapi-template-feature
   ```

4. **Test template generation** (before release)
   ```bash
   # Generate templatized version
   ./scripts/templatize.sh

   # Test generation
   copier copy .templatized/ /tmp/test-project --trust
   cd /tmp/test-project
   uv run pytest
   ```

### Release Process

When a release is created:

1. GitHub Actions runs the templatization workflow
2. The workflow generates `redact_api` variables from `redact_api/`
3. The templatized version is pushed to the `copier` branch
4. External users can then generate from `--vcs-ref copier`

### File Structure

```
fastapi-template/
├── redact_api/         # Runnable Python package (main branch)
│   ├── api/
│   ├── models/
│   ├── services/
│   └── main.py
├── tests/                    # Tests for the template
├── scripts/
│   ├── templatize.sh        # Generate template from runnable code
│   └── ...
├── copier.yaml              # Copier configuration
├── _tasks.py                # Post-generation tasks
└── .github/workflows/       # CI/CD including templatization
```

---

## Instance Management (For Generated Projects)

Once you've generated a project, you can track and update it:

### Tracking Template Versions

Generated projects contain a `.copier-answers.yml` file that tracks:
- Source template location
- Template version (commit hash)
- Configuration choices made during generation

### Updating a Generated Project

To pull in template improvements:

```bash
cd /path/to/your-project

# Check current status
git status  # Should be clean

# Pull template changes
copier update --trust

# Run verification
uv run ruff check .
uv run mypy .
uv run pytest

# Commit the update
git commit -m "Merge template improvements"
```

### Drift Checking

Monitor if your project is behind the template:

```bash
# Check single project
./scripts/check-instance-drift.sh /path/to/your-project
```

**Output** (up-to-date):
```
Up-to-date
```

**Output** (behind):
```
Instance is 5 commits behind template

Recent template changes:
abc123d Fix user email validation
def456e Add international email support
789abcd Security patch: input validation

To update: cd "/path/to/your-project" && copier update --trust
```

---

## Handling Updates and Conflicts

### Standard Update (Backward-Compatible Changes)

```bash
cd /path/to/your-project

# Check current status
git status  # Should be clean

# Pull template changes
copier update --trust

# Run verification
uv run ruff check .
uv run mypy .
uv run pytest

# Commit the update
git commit -m "Merge template improvements"
```

### Conflict Resolution

If `copier update` detects conflicts:

```bash
cd /path/to/your-project
copier update --trust
# Conflict detected!

# Check status
git status

# Resolve conflicts
vim <conflicted-file>
# Edit conflict markers (<<<<<<<, =======, >>>>>>>)

# Mark as resolved
git add <conflicted-file>

# Complete merge
git commit -m "Merge template changes, resolve conflicts"

# Verify
uv run pytest
```

**Tips**:
- Template often has best practices - prefer template version
- Document why project customization is needed
- Consider contributing customizations back to template

---

## Update Schedule

Recommended update cadence for generated projects:

| Update Type | Frequency | Urgency | Example |
|-------------|-----------|---------|---------|
| Security patches | Within 1 week | Critical | Auth bypass, SQL injection |
| Bug fixes | Within 2 weeks | High | Validation bug, logic error |
| Features | Within 1 month | Medium | New utility, performance improvement |
| Breaking changes | As needed | High | Major dependency upgrade, API redesign |

---

## Contributing Back

If you discover a bug or pattern in your project that would help others:

1. **Verify it's general** - Not specific to your business domain
2. **Create a PR against main branch** - Work directly on the runnable code
3. **Test thoroughly** - Run full test suite
4. **Document the change** - Update docs if needed

Example: If you improve email validation:

```python
# In your project: my_service/models/validators.py
def validate_email(email: str) -> bool:
    """Handle international domains and plus-addressing."""
    # ... your implementation

# Contribute to template: redact_api/models/validators.py
# Same implementation, contributes to the runnable code
```

---

## Resources

- **Setup Guide**: See template [README.md](README.md)
- **Configuration**: See [CONFIGURATION-GUIDE.md](CONFIGURATION-GUIDE.md)
- **Quick Start**: See [QUICKSTART.md](QUICKSTART.md)
- **Python Patterns**: See [PYTHON-PATTERNS.md](PYTHON-PATTERNS.md)

---

## Deprecated: Test Instance Workflow

The following commands from `manage-test-instance.sh` are **deprecated** and will be removed in a future release:

- `generate` - No longer needed, work directly on main branch
- `verify` - Run verification commands directly
- `sync` - No instances to sync
- `reverse-sync` - Not needed, make changes directly to code

The script remains available for backwards compatibility but is not recommended for new development.
