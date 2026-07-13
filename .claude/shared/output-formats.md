# Code Review Output Formats - Backend

Standard formats for backend code review findings.

## Quick Review (<5 files)

```markdown
# Code Review: [Feature Name]

## Status
✅ No issues found. Ready to merge.

- Ruff: ✅ 0 violations
- MyPy: ✅ 0 errors
- Pytest: ✅ 24/24 passing
```

Or if issues:

```markdown
# Code Review: [Feature Name]

## Findings

### Missing Type Annotation
- **File**: `app/services/user_service.py:45`
- **Problem**: Function missing return type annotation
- **Fix**: Add `-> User` to function signature

### SQL Injection Risk
- **File**: `app/api/users.py:123`
- **Problem**: Unsanitized user input in query
- **Fix**: Use SQLAlchemy parameterized queries

## Status
- ❌ Ruff: 2 violations
- ✅ MyPy: 0 errors
- ✅ Pytest: 24/24 passing
```

## Standard Review (5-20 files)

```markdown
# Code Review: [Feature Name]

## Findings by Severity

### 🚨 Critical Issues (Must Fix)

#### SQL Injection Vulnerability
- **File**: `app/services/search.py:67`
- **Problem**: User input directly interpolated in SQL query
- **Impact**: Database compromise possible
- **Fix**:
```python
# Before
query = f"SELECT * FROM users WHERE email = '{email}'"

# After
query = select(User).where(User.email == email)
```

### ⚠️ Major Concerns (Should Fix)

#### Missing Async on Database Call
- **File**: `app/api/products.py:89`
- **Problem**: Using sync `.all()` instead of async execute
- **Impact**: Blocks event loop, poor performance
- **Fix**: Use `await db.execute(select(Product)).scalars().all()`

### ℹ️ Low Priority (Will Fix)

- **Error messages inline**: Extract to variables (EM101 rule)

## Summary

- **Findings**: 1 critical, 1 major, 1 low
- **Ruff**: ❌ 3 violations
- **MyPy**: ✅ 0 errors
- **Pytest**: ✅ 42/42 passing
- **Status**: ⚠️ CHANGES NEEDED
```

## Backend-Specific Findings

### Database Issues

```markdown
#### N+1 Query Pattern
- **File**: `app/services/order_service.py:123`
- **Problem**: Querying items in loop - generates N+1 queries
- **Fix**:
```python
# Before (N+1 queries)
orders = await db.execute(select(Order))
for order in orders.scalars():
    items = await db.execute(select(Item).where(Item.order_id == order.id))

# After (1 query with eager loading)
orders = await db.execute(
    select(Order).options(selectinload(Order.items))
)
```
```

### Async Issues

```markdown
#### Blocking Call in Async Function
- **File**: `app/services/file_service.py:56`
- **Problem**: Using sync `open()` in async function
- **Fix**: Use `aiofiles` library for async file I/O
```

---

Reference parent `workspace/.claude/shared/output-formats.md` for general format guidelines.
