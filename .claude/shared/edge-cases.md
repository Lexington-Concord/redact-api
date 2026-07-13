# Backend Edge Cases

Edge cases specific to Python FastAPI backend testing.

## FastAPI/Pydantic Validation

- **Missing required fields** - Pydantic raises ValidationError (422)
- **Wrong field types** - String when int expected
- **Field constraints** - min_length, max_length, ge, le violations
- **Email format** - Invalid email syntax
- **Enum values** - Value not in enum
- **Nested model validation** - Deep object validation

## Database (SQLAlchemy)

- **Unique constraint violations** - Duplicate email/username (409)
- **Foreign key violations** - Referenced entity doesn't exist
- **NULL constraints** - Required field is NULL
- **Concurrent modifications** - Two requests updating same row
- **Transaction rollback** - Error mid-transaction
- **Session state** - Detached objects, stale data

## Authentication & Authorization

- **Missing token** - No Authorization header (401)
- **Invalid token format** - Malformed JWT
- **Expired token** - Token past expiration time
- **Wrong signature** - Token with invalid signature
- **Insufficient permissions** - User lacks required role (403)
- **Inactive user** - User account disabled

## Async/Database Sessions

- **Session not committed** - Changes lost if not committed
- **Using committed session** - Session closed/expired
- **Concurrent session usage** - Session used in multiple coroutines
- **Blocking in async** - Sync database call in async function

## API Endpoints

- **Path parameter types** - Invalid int in path (e.g., `/users/abc`)
- **Query parameter validation** - Invalid values in query string
- **Request body size** - Exceeding max request size
- **Missing Content-Type** - No application/json header
- **Malformed JSON** - Invalid JSON in request body

## Pagination

- **Page/offset out of bounds** - Requesting page beyond data
- **Negative page/limit** - page=-1, limit=-10
- **Zero or very large limit** - limit=0, limit=1000000
- **Concurrent data changes** - Items added/removed during pagination

## File Uploads (if applicable)

- **File too large** - Exceeding max file size
- **Wrong file type** - PDF when image expected
- **Empty file** - 0 bytes
- **Malicious file** - File with executable code

## Error Handling

- **Database connection lost** - Mid-request DB failure
- **External service timeout** - Third-party API unreachable
- **Rate limit exceeded** - Too many requests
- **Validation error with multiple fields** - Return all errors, not just first

---

Reference parent `workspace/.claude/shared/edge-cases.md` for general edge cases.
