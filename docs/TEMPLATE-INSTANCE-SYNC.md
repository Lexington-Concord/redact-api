# Template-Instance Sync Strategy

> **Deprecation Notice**: This document describes the old template-first workflow.
> With the new **runnable-first architecture**, test instances are no longer needed during development.
> See [INSTANCES.md](../INSTANCES.md) for the current deployment workflow.
> This document is preserved for reference and for managing generated projects.

---

Comprehensive guide for bidirectional learning between the fastapi-template and its instances.

## Overview

This template uses **Copier's git-based update mechanism** to enable bidirectional learning:

- **Template → Instances** (automated): `copier update` pulls template improvements into existing instances
- **Instances → Template** (manual): Extract successful patterns from instances back into template

This document describes both workflows and best practices for managing multiple instances.

---

## Part 1: Copier Update Mechanism

### How Copier Update Works

Copier's `update` command performs a **three-way git merge**:

1. **Base** = Previous template version that generated this instance (stored in `.copier-answers.yml`)
2. **Theirs** = Current template version (HEAD)
3. **Ours** = Current instance version (what you've customized)

Copier merges these three versions intelligently:
- Applies template changes (Theirs)
- Preserves instance customizations (Ours)
- Detects conflicts where both sides changed the same code

### Example: Merging a Bug Fix

**Scenario**: The template has a bug in the user validation that you discovered and fixed in your production instance. The template maintainers then fix the same bug.

**Before**: Instance is customized, template is outdated
```
Base (old template):
  def validate_email(email):
    if not "@" in email:  # BUG: incorrect validation
      return False
    return True

Instance (your fix):
  def validate_email(email):
    if "@" not in email:  # You fixed this
      return False
    if email.count("@") != 1:  # You added this check too
      return False
    return True

Template (maintainer's fix):
  def validate_email(email):
    if "@" not in email:  # Fixed syntax
      return False
    return True
```

**After copier update**:
```
def validate_email(email):
  if "@" not in email:  # Template's fix applied
    return False
  if email.count("@") != 1:  # Your customization preserved!
    return False
  return True
```

Both the template's fix and your customization are preserved!

### `.copier-answers.yml` Tracking

Copier stores metadata about the instance:

```yaml
_src_path: $HOME/workspace/meta-work/fastapi-template
_commit: abc123def456  # Last template commit that was applied
project_name: FastAPI Template Test
project_slug: redact_api_test
description: Test instance for template verification
port: 8100
```

When you run `copier update`:
1. Copier reads `_commit: abc123def456`
2. Calculates diff: `template@abc123def456..template@HEAD`
3. Applies only the changes, not the full template
4. Updates `_commit` to current HEAD

---

## Part 2: Template → Instance Updates

### Workflow: Applying Template Changes

#### Step 1: Verify Template Changes Work

Always test in the persistent test instance first:

```bash
# Modify template source
cd $HOME/workspace/meta-work/fastapi-template
vim "redact_api/services/user_service.py"

# Commit template change
git commit -m "Fix user email validation"

# Pull changes into test instance
/test-instance sync

# Verify everything still works
/test-instance verify
```

#### Step 2: Update Production Instances

Once verified in test instance, apply to production instances:

```bash
# For each production instance
cd /path/to/production-api
copier update --trust

# Test in production context
pytest
uv run mypy .
uv run ruff check .

# Commit the merge
git commit -m "Merge template improvements"
```

#### Step 3: Track Updates

Update `INSTANCES.md` registry:

```markdown
| Project | Location | Last Updated | Template Commit | Status |
|---------|----------|--------------|-----------------|--------|
| users-api | /projects/users-api | 2026-01-07 | abc123d | ✅ Up-to-date |
```

### Conflict Resolution

If `copier update` encounters conflicts:

```bash
cd /path/to/instance
copier update --trust
# Conflicts detected!

# Check status
git status
# Shows conflicted files with merge conflict markers

# Edit conflicted files
vim app/services/user_service.py
# Resolve <<<<<<<, =======, >>>>>>> markers

# Mark as resolved
git add app/services/user_service.py

# Complete merge
git commit -m "Merge template changes, resolve conflicts"

# Verify
pytest
```

### Type of Template Changes

**Safe to apply automatically:**
- ✅ Bug fixes (validation, logic errors)
- ✅ Security patches (authentication, validation)
- ✅ Performance improvements (indexing, queries)
- ✅ New utility functions (no breaking changes)
- ✅ Dependency upgrades with compatibility

**Require careful review:**
- ⚠️ API changes (breaking endpoint changes)
- ⚠️ Database schema changes (migrations)
- ⚠️ Major dependency upgrades
- ⚠️ Configuration changes
- ⚠️ New required parameters

**Should not apply automatically:**
- ❌ Business logic specific to template
- ❌ Refactoring that changes patterns significantly
- ❌ Removing features

### Breaking Change Handling

When a template change is breaking:

1. **Document migration path** in template CHANGELOG
2. **Test extensively** in test instance
3. **Release as version tag**: `git tag v2.0.0-breaking`
4. **Contact instance owners** with migration instructions
5. **Provide migration script** if possible

Example: SQLModel v1.0 upgrade requiring async session refactoring

```bash
# In template CHANGELOG.md
## v2.0.0 - Breaking Changes

### SQLModel 1.0.0 Upgrade

Requires session management refactoring:

```python
# OLD (v1.x)
session = SessionLocal()
user = session.exec(select(User)).first()

# NEW (v2.0+)
async with SessionLocal() as session:
    user = await session.exec(select(User)).first()
```

See `docs/MIGRATION-v1-to-v2.md` for detailed steps.
```

Then update instances:

```bash
cd /path/to/instance

# Read migration guide
cat /path/to/template/docs/MIGRATION-v1-to-v2.md

# Apply migration (manual refactoring or provided script)
./scripts/migrate-to-v2.0.sh

# Test thoroughly
pytest
uv run mypy .

# Update
copier update --trust

# Verify
pytest
```

---

## Part 3: Instance → Template Learning

### Identifying Patterns Worth Extracting

**Criteria for extraction into template:**

✅ **Extract if:**
- Pattern is repeated across multiple instances
- Solves a common problem (validation, permission checks, error handling)
- Improves security or performance
- Is a general best practice
- Works with template's architecture

❌ **Don't extract if:**
- Business logic specific to one domain
- Highly customized for specific use case
- Would add unnecessary complexity to template
- Breaking change for existing instances

### Example: Extracting a Validation Pattern

**Discovery**: Across 3 instances, you see identical email validation with UTF-8 support:

```python
# Instance 1 (users-api)
def validate_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    local, domain = email.rsplit("@", 1)
    if len(local) > 64 or len(domain) > 255:
        return False
    # UTF-8 support for international emails
    try:
        email.encode("ascii").decode("ascii")  # Check ASCII-compatible
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            email.encode("utf-8").decode("utf-8")  # Check UTF-8
        except:
            return False
    return True
```

**Extraction Process**:

1. **Generalize** - Add to template as utility validator
2. **Jinja-templatize** - If it needs customization
3. **Test** - Verify with test instance
4. **Document** - Explain when to use
5. **Propagate** - Add to other instances

**Result** in template:

```python
# redact_api/models/validators.py

from typing import Annotated

from pydantic import PlainValidator


def validate_email_with_international_support(email: str) -> str:
    """Validate email with UTF-8 support for international addresses.

    Args:
        email: Email address to validate

    Returns:
        Validated email

    Raises:
        ValueError: If email is invalid
    """
    if not email or "@" not in email:
        raise ValueError("Email must contain @")

    local, domain = email.rsplit("@", 1)
    if len(local) > 64 or len(domain) > 255:
        raise ValueError("Email parts exceed maximum length")

    # Support both ASCII and UTF-8
    try:
        email.encode("ascii").decode("ascii")
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            email.encode("utf-8").decode("utf-8")
        except:
            raise ValueError("Email contains invalid characters")

    return email


Email = Annotated[str, PlainValidator(validate_email_with_international_support)]
```

Then use in models:

```python
# redact_api/models/user.py

from pydantic import BaseModel
from .validators import Email


class UserCreate(BaseModel):
    email: Email
    password: str
```

**Test in test instance**:

```bash
/test-instance sync
/test-instance verify

# Manually test
cd fastapi-template-test-instance
python
>>> from redact_api_test.models.validators import validate_email_with_international_support
>>> validate_email_with_international_support("user@example.com")
'user@example.com'
>>> validate_email_with_international_support("user+tag@example.com")
'user+tag@example.com'
>>> validate_email_with_international_support("користувач@приклад.укр")
'користувач@приклад.укр'
```

**Propagate to other instances**:

```bash
# After merging into template
for instance in /projects/users-api /projects/orders-api; do
    cd "$instance"
    copier update --trust
    pytest
done
```

### Authentication Provider Validators

Different authentication providers require different validation. Here are examples for common providers:

```python
# redact_api/models/validators.py

# When using Ory authentication:
def validate_ory_user_id(user_id: str) -> str:
    """Validate Ory user ID format."""
    if not user_id.startswith("identity/"):
        raise ValueError("Ory user ID must start with 'identity/'")
    return user_id

# When using AWS Cognito authentication:
def validate_cognito_user_id(user_id: str) -> str:
    """Validate AWS Cognito user ID format."""
    # Different validation for Cognito
    return user_id
```

Choose the appropriate validator based on your authentication provider.

---

## Part 4: Multi-Instance Management

### Instance Registry

Track all instances for coordinated updates and maintenance.

**File**: `INSTANCES.md`

```markdown
# FastAPI Template Instances

| Project | Location | Team | Last Updated | Template Version | Status |
|---------|----------|------|--------------|------------------|--------|
| test-instance | /workspace/meta-work/ | Template Maintainers | 2026-01-07 | HEAD | ✅ Up-to-date |
| users-api | /projects/users-api | Platform Team | 2026-01-06 | abc123d | ✅ Up-to-date |
| orders-api | /projects/orders-api | Commerce Team | 2025-12-20 | e4f5a6b | ⚠️ 18 commits behind |
| payments-api | /projects/payments-api | Finance Team | 2025-11-01 | old_hash | 🔴 Major version behind |
```

### Drift Checking

Monitor which instances need updates:

**Script**: `scripts/check-instance-drift.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

INSTANCE_DIR="${1:?Usage: $0 <instance-path>}"
TEMPLATE_DIR="$(dirname "$0")/.."

TEMPLATE_COMMIT=$(git -C "$TEMPLATE_DIR" rev-parse HEAD)
INSTANCE_COMMIT=$(grep "_commit:" "$INSTANCE_DIR/.copier-answers.yml" | awk '{print $2}')

if [[ "$TEMPLATE_COMMIT" == "$INSTANCE_COMMIT" ]]; then
  echo "✅ Up-to-date"
  exit 0
fi

COMMITS_BEHIND=$(git -C "$TEMPLATE_DIR" rev-list --count "$INSTANCE_COMMIT".."$TEMPLATE_COMMIT")
echo "⚠️  Instance is $COMMITS_BEHIND commits behind template"
echo ""
echo "Recent template changes:"
git -C "$TEMPLATE_DIR" log --oneline --no-decorate "$INSTANCE_COMMIT".."$TEMPLATE_COMMIT"
echo ""
echo "To update: cd \"$INSTANCE_DIR\" && copier update --trust"
```

**Check all instances**:

```bash
#!/usr/bin/env bash
# check-all-drifts.sh

INSTANCES=(
  "/path/to/users-api"
  "/path/to/orders-api"
  "/path/to/payments-api"
)

for instance in "${INSTANCES[@]}"; do
  echo "Checking $instance"
  ./scripts/check-instance-drift.sh "$instance"
  echo ""
done
```

### Coordinated Update Strategy

For breaking changes affecting multiple instances:

1. **Announce** - Notify all instance owners
2. **Test** - Verify in test instance thoroughly
3. **Document** - Provide migration guide
4. **Schedule** - Coordinate update timeline
5. **Execute** - Update instances sequentially
6. **Verify** - Run full test suite in each
7. **Document** - Update INSTANCES.md

**Example**: Async migration affecting all instances

```bash
# Announce in #engineering
# "Template v2.0.0 upgrade available - requires async refactoring"

# Create migration docs
./docs/MIGRATION-v1-to-v2.md
git tag v2.0.0-breaking

# Notify instance teams
# "Your team should update within 2 weeks"
# "See docs/MIGRATION-v1-to-v2.md for steps"

# Update test instance first
/test-instance sync
/test-instance verify

# Stagger updates across teams
# Week 1: users-api, orders-api (non-critical path)
# Week 2: payments-api (careful, business-critical)

# For each instance:
cd /path/to/instance
copier update --trust
pytest
# Manual testing
git push
```

---

## Part 5: Best Practices

### Template Development

1. **Always test before committing**
   ```bash
   /test-instance sync
   /test-instance verify
   git commit  # Only if verify passes
   ```

2. **Provide migration guides for breaking changes**
   - Document what changed
   - Show before/after code
   - Provide automated migration script if possible
   - Test migration in instances

3. **Keep template DRY**
   - Extract repeated patterns from instances
   - Generalize with Jinja2 when needed
   - Add documentation and examples

4. **Version strategically**
   - Minor versions: backward-compatible improvements
   - Major versions: breaking changes
   - Tag releases: `git tag v1.2.3`
   - Update INSTANCES.md after releases

### Instance Management

1. **Keep instances reasonably close to template**
   - Update at least monthly
   - Don't defer breaking changes indefinitely
   - Set update policy for your team

2. **Minimize instance customization**
   - Extract customizations back to template when generic
   - Use instance-specific config, not hardcoded values
   - Document why customization is needed

3. **Test after updates**
   - Run full test suite
   - Manual smoke test of critical features
   - Check for deprecation warnings

4. **Track instance configuration**
   - `.copier-answers.yml` version-controlled
   - Document non-template customizations
   - Include in onboarding docs

### Conflict Resolution

1. **Prefer template changes when possible**
   - Template version often has best practices
   - Instance customization is usually less general

2. **Communicate with template maintainers**
   - If instance improvement is general, suggest upstreaming
   - If template change doesn't work, report issue
   - Share learnings to improve template

3. **Keep conflict markers until resolved**
   - Don't blindly accept one side
   - Merge intelligently (both changes often better)
   - Test thoroughly after resolving

---

## Part 6: Automated Reverse Sync (Instance → Template)

### Overview

The test instance script provides an automated **reverse sync** command to safely copy fixes from a test instance back to the template. This prevents fixes from being lost when instances are deleted.

### When to Use Reverse Sync

Use `reverse-sync` when you've fixed errors in the test instance that should apply to all future instances:

✅ **Use for:**
- Linting fixes (ruff violations)
- Type checking fixes (mypy errors)
- Test improvements
- Bug fixes in shared logic
- New utility functions
- Documentation improvements

❌ **Don't use for:**
- Instance-specific configurations
- Business logic specific to one service
- Changes requiring new template variables

### Quick Start

```bash
cd fastapi-template

# Fix errors in test instance
cd ../fastapi-template-test-instance
# ... make fixes ...

# Sync back to template
cd ../fastapi-template
./scripts/manage-test-instance.sh reverse-sync
```

### Command Usage

#### Interactive Mode (Default)

```bash
./scripts/manage-test-instance.sh reverse-sync
```

Shows each changed file, displays the diff, and prompts for approval:

```
Found 7 file(s) to sync

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
File 1/7: redact_api_test/core/http_client.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Template path: redact_api/core/http_client.py

Changes:
-from datetime import datetime

 import httpx

Sync this file? (y/n/q) y
✓ Applied to template
```

Options at the prompt:
- `y` - Sync this file to template
- `n` - Skip this file
- `q` - Cancel remaining files

#### Auto Mode

```bash
./scripts/manage-test-instance.sh reverse-sync --auto
```

Syncs all changed files without prompts. Useful for CI or when you're confident in your changes.

### How It Works

**Step-by-step process:**

1. **Validation**
   - Checks test instance exists
   - Ensures template repo has no uncommitted changes
   - Lists changed files (excluding uv.lock, uploads/, etc.)

2. **Interactive Review** (unless `--auto`)
   - Shows each file's diff
   - Maps instance paths to template paths (`redact_api_test/` → `redact_api/`)
   - Asks for approval

3. **Path Transformation**
   - Converts instance-specific paths to Jinja2 template variables
   - Example: `redact_api_test/models/user.py` → `redact_api/models/user.py`

4. **Patch Application**
   - Creates git patches from instance changes
   - Applies patches to template files
   - Rolls back automatically if application fails

5. **Roundtrip Verification** (Critical Safety Check)
   - Applies modified template back to test instance via `copier update`
   - Verifies changes survive template transformation
   - Ensures Jinja2 variables are correctly handled
   - Detects if transformation breaks something

6. **Quality Checks**
   - Runs `ruff check` in test instance
   - Runs `mypy` for type checking
   - Runs `pytest` for all tests
   - Warns if any checks fail (you can choose to proceed anyway)

7. **Summary & Next Steps**
   - Shows files synced
   - Displays template diff
   - Suggests git commands for commit

### Example Workflows

#### Fix a Linting Error

```bash
# In test instance, fix a ruff violation
cd fastapi-template-test-instance
# ... edit files ...

# Verify fix works
uv run ruff check .

# Back to template, sync the fix
cd ../fastapi-template
./scripts/manage-test-instance.sh reverse-sync
# → Select 'y' for files to sync
# → Watch roundtrip verification
# → Commit when all checks pass

git commit -m "Fix ruff violations from test instance"
```

#### Multiple File Sync

```bash
# Fix multiple issues in test instance
cd fastapi-template-test-instance
# ... fix 5 different files ...

# Sync all at once
cd ../fastapi-template
./scripts/manage-test-instance.sh reverse-sync --auto

# Review all changes
git diff

# Commit if satisfied
git commit -am "Apply fixes from test instance"
```

#### Selective Sync

To sync only specific files:

```bash
cd fastapi-template
./scripts/manage-test-instance.sh reverse-sync
# At each prompt, say 'y' for files you want, 'n' for others
# Say 'q' when done
```

### What Gets Excluded

The script automatically skips files that shouldn't be synced:

- `uv.lock` - Regenerated by each instance
- `uploads/` - Runtime uploads directory
- `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/` - Build artifacts
- Untracked files (e.g., `.env`)

### Error Handling

#### "Template has uncommitted changes"

```
Error: Template has uncommitted changes
Info: Either commit them or stash: git stash
```

**Solution**: Commit or stash template changes first

```bash
git add .
git commit -m "WIP"
# Then retry reverse-sync
```

#### "Roundtrip failed"

```
Error: Roundtrip failed - template changes produced unexpected diffs
Info: Rolling back template changes...
```

**Meaning**: Changes don't survive template transformation. Possible causes:
- Jinja2 variable handling issue
- Path mapping error
- Instance-specific code that shouldn't be in template

**Solution**:
1. Manually inspect the changes
2. Edit the template to make them Jinja2-compatible
3. Re-run reverse-sync

#### "Quality checks failed"

```
Warning: Quality checks failed - template changes may have issues
Info: Commit template changes anyway? (y/n)
```

**Meaning**: Ruff/mypy/pytest failed after roundtrip

**Solution**:
- Answer 'n' to abort and fix issues
- Or answer 'y' to proceed anyway (not recommended)
- Fix issues in template and re-run reverse-sync

### Troubleshooting

#### Changes Won't Apply

If `git apply` fails on a patch:

```
Error: Failed to apply patch for: redact_api/core/auth.py
```

**Possible causes:**
- Template file differs from instance file
- Patch has merge conflicts
- File structure changed between versions

**Solution:**
- Manually merge the changes in template
- Or: Copy file content manually, then use reverse-sync for simpler changes

#### Roundtrip Shows Unexpected Changes

If copier update produces diffs:

```
Unexpected changes after copier update:
redact_api/models/user.py | 15 ++++++---
```

**Possible causes:**
- Jinja2 templating issues
- Instance had instance-specific changes
- Template has variables you're not handling

**Solution:**
- Review both template and instance versions
- Ensure Jinja2 variables are consistent
- Consider if this code should be in template at all

### Best Practices

1. **Keep changes in test instance committed**
   ```bash
   git add .
   git commit -m "Fix: remove unused imports"
   ```
   This helps reverse-sync detect what changed.

2. **Sync frequently**
   - Don't let changes pile up
   - Smaller changes are easier to review and debug

3. **Review before committing**
   ```bash
   git diff  # Review changes in template
   git commit -p  # Stage changes interactively
   ```

4. **Test the changes**
   - Always run `verify` after reverse-sync
   - Manually test if needed

5. **Document template changes**
   - Add comments if template changes are non-obvious
   - Update CHANGELOG if breaking changes

### When to Not Use Reverse Sync

Consider NOT syncing these changes:

- **Instance customization**: Service-specific config, domain logic
- **Breaking changes**: New required fields, changed API signatures
- **Third-party code**: Vendored dependencies, generated code
- **CI/CD specific**: Build scripts for specific deployments

Instead, create a new feature in the template with proper Jinja2 variables and documentation.

---

## Part 7: Troubleshooting

### "Copier Update Fails"

**Problem**: `copier update` errors

**Solution**:
1. Check `.copier-answers.yml` exists
2. Verify `_commit` hash exists in template repo
3. Check for uncommitted changes: `git status`
4. Try: `copier update --trust --overwrite`

### "Merge Conflicts Too Complex"

**Problem**: Too many conflicts, hard to resolve

**Solution**:
1. Start over: `git merge --abort`
2. Consult template maintainers
3. Consider manual update:
   ```bash
   git checkout ours  # Keep current version
   git add .
   git commit -m "Keeping current version, will manually merge"
   ```

### "Instance Gets Out of Sync"

**Problem**: Instance is months behind template

**Solution**:
1. Check drift: `./scripts/check-instance-drift.sh`
2. Review what changed: `git -C /template log --oneline <commit>..<commit>`
3. Update incrementally if breaking changes
4. Or recreate from template if simpler

### "Template Change Breaks Instance"

**Problem**: After update, instance fails tests

**Solution**:
1. Don't panic - this is why we test!
2. Identify what broke: `pytest -vv`
3. Either:
   - Fix template bug and sync again
   - Resolve conflict manually and commit
4. Report issue to template maintainers
5. Update INSTANCES.md with status

---

## Summary

The template-instance sync strategy enables:

- **Efficient scaling** - Template improvements propagate automatically
- **Bidirectional learning** - Instances teach template, template improves instances
- **Conflict-free updates** - Git merge handles most conflicts intelligently
- **Version control** - Track exactly which template version generated each instance
- **Team coordination** - Registry and drift checker help manage multiple instances

**Key takeaway**: Think of template and instances as **two parts of the same ecosystem**, not separate concerns.
