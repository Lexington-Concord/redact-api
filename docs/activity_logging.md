# Activity Logging Guide

Comprehensive guide for implementing and using activity logging in the FastAPI application.

## Overview

Activity logging provides an audit trail of all important operations in the system. Each activity log entry captures:

- **What**: Action performed (CREATE, UPDATE, DELETE, READ)
- **Who**: User ID who performed the action
- **When**: Timestamp of the action
- **Where**: Organization ID (for multi-tenant isolation)
- **Context**: Request ID for request tracing
- **Why**: Additional details or metadata about the operation

## Architecture

### Components

1. **ActivityLog Model**: Database table storing audit events
2. **ActivityAction Enum**: Predefined action types
3. **log_activity() Function**: Core logging mechanism
4. **log_activity_decorator()**: Decorator for automatic logging on endpoints
5. **Activity Logging Middleware**: Automatic context propagation

### Data Flow

```
Request arrives
↓
TenantIsolationMiddleware extracts tenant context
↓
RequestContextMiddleware captures request_id, user_id
↓
Endpoint executes
↓
log_activity() called (manually or via decorator)
↓
Context automatically inherited from request
↓
ActivityLog stored with all metadata
```

## Usage Patterns

### Pattern 1: Automatic Logging with Decorator

```python
from redact_api.core.activity_logging import ActivityAction, log_activity_decorator

@router.post("", response_model=UserRead, status_code=201)
@log_activity_decorator(ActivityAction.CREATE, "user")
async def create_user_endpoint(
    payload: UserCreate,
    session: SessionDep,
) -> User:
    """Create user with automatic activity logging."""
    user = User(**payload.model_dump())
    session.add(user)
    await session.commit()
    # Activity log automatically created with:
    # - action: CREATE
    # - resource_type: "user"
    # - resource_id: user.id (from response)
    # - user_id: extracted from request context
    # - organization_id: extracted from request context
    # - request_id: extracted from request context
    return user

@router.delete("/{user_id}", status_code=204)
@log_activity_decorator(
    ActivityAction.DELETE, "user",
    resource_id_param_name="user_id"  # For 204 responses with no body
)
async def delete_user_endpoint(
    user_id: UUID,
    session: SessionDep,
) -> None:
    """Delete user with activity logging."""
    user = await get_user(session, user_id)
    await session.delete(user)
    await session.commit()
    # Activity log created with resource_id from path parameter
```

### Pattern 2: Manual Logging in Business Logic

```python
from redact_api.core.activity_logging import log_activity, ActivityAction

async def archive_document(
    session: AsyncSession,
    document_id: UUID,
    tenant: TenantContext,
) -> None:
    """Archive document with activity logging."""
    document = await get_document(session, document_id)
    document.archived_at = datetime.utcnow()
    session.add(document)
    await session.commit()

    # Log activity with transactional consistency
    await log_activity(
        action=ActivityAction.UPDATE,
        resource_type="document",
        resource_id=document_id,
        details={"action": "archive"},
        session=session,  # Uses same transaction
    )
```

### Pattern 3: Fire-and-Forget Logging for Background Tasks

```python
from redact_api.core.activity_logging import log_activity, ActivityAction

async def send_email_notification(user_id: UUID, email: str) -> None:
    """Background task - log independently from request."""
    try:
        # Send email logic...
        pass
    finally:
        # Log after email sent (success or failure)
        await log_activity(
            action=ActivityAction.CREATE,
            resource_type="notification",
            details={
                "type": "email",
                "recipient": email,
                "success": True,
            },
            # No session provided - logs in separate transaction
        )
```

## Request Context Inheritance

The activity logging system automatically inherits context from the HTTP request:

### Extracted Fields

| Field | Source | Purpose |
|-------|--------|---------|
| `user_id` | JWT token claims via AuthMiddleware | Identifies who performed action |
| `organization_id` | TenantIsolationMiddleware | Multi-tenant data isolation |
| `request_id` | x-request-id header or generated | Request correlation/tracing |
| `ip_address` | Request headers | Audit trail IP tracking |
| `user_agent` | Request headers | Browser/client identification |

### Accessing in Endpoints

Context is automatically available via dependency injection:

```python
from redact_api.core.logging import get_logging_context

@router.post("/documents")
async def create_document(
    file: UploadFile,
    session: SessionDep,
    tenant: TenantDep,
) -> DocumentRead:
    """Access request context in endpoint."""
    # Get full context
    context = get_logging_context()
    print(context)
    # {
    #     "user_id": "550e8400-e29b-41d4-a716-446655440000",
    #     "organization_id": "550e8400-e29b-41d4-a716-446655440001",
    #     "request_id": "req-abc123def456",
    #     "ip_address": "192.0.2.1",
    # }

    # ... create document ...

    # Context automatically included in activity log
    await log_activity(
        action=ActivityAction.CREATE,
        resource_type="document",
        resource_id=document.id,
        session=session,
    )
    # Activity log will contain:
    # - user_id, organization_id, request_id from context
    # - Plus any additional fields from details
```

## Activity Log Schema

### Database Fields

```sql
CREATE TABLE activity_log (
    id UUID PRIMARY KEY,
    action VARCHAR(20) NOT NULL,           -- CREATE, READ, UPDATE, DELETE
    resource_type VARCHAR(100) NOT NULL,   -- "user", "document", "organization"
    resource_id UUID,                      -- ID of affected resource
    user_id UUID NOT NULL,                 -- Who performed the action
    organization_id UUID NOT NULL,         -- Tenant/organization context
    request_id VARCHAR(255),               -- HTTP request ID for tracing
    details JSONB,                         -- Additional metadata
    ip_address VARCHAR(45),                -- Source IP address
    user_agent VARCHAR(500),               -- Client user agent
    created_at TIMESTAMP NOT NULL,         -- When action occurred
    updated_at TIMESTAMP NOT NULL          -- Last modified (soft deletes)
);
```

### JSON Details Field

The `details` field stores operation-specific metadata:

```python
# Document upload
details = {
    "filename": "report.pdf",
    "size_bytes": 1024000,
    "content_type": "application/pdf",
    "tags": ["report", "financial"],
}

# User update
details = {
    "fields_changed": ["name", "email"],
    "old_email": "old@example.com",
    "new_email": "new@example.com",
}

# Batch operation
details = {
    "batch_id": "batch-123",
    "count": 50,
    "duration_seconds": 2.5,
}

# Error scenario
details = {
    "error_type": "ValidationError",
    "error_message": "Invalid email format",
    "attempted_value": "invalid-email",
}
```

## Query Examples

### Audit Trail for User

```python
# All actions by specific user
stmt = select(ActivityLog).where(
    ActivityLog.user_id == target_user_id
).order_by(ActivityLog.created_at.desc())
results = await session.execute(stmt)
actions = results.scalars().all()
```

### Changes to Resource

```python
# All changes to a document
stmt = select(ActivityLog).where(
    (ActivityLog.resource_type == "document")
    & (ActivityLog.resource_id == document_id)
).order_by(ActivityLog.created_at)
results = await session.execute(stmt)
changes = results.scalars().all()
```

### Recent Activity for Organization

```python
# Last 100 actions in organization
stmt = select(ActivityLog).where(
    ActivityLog.organization_id == org_id
).order_by(
    ActivityLog.created_at.desc()
).limit(100)
results = await session.execute(stmt)
recent = results.scalars().all()
```

### Activity Report

```python
from sqlalchemy import func

# Count actions by type
stmt = select(
    ActivityLog.action,
    func.count().label("count")
).where(
    ActivityLog.organization_id == org_id
).group_by(
    ActivityLog.action
)
results = await session.execute(stmt)
summary = results.all()
# [("CREATE", 150), ("UPDATE", 42), ("DELETE", 5)]
```

## Best Practices

### 1. Log Business Operations, Not Technical Details

```python
# GOOD: Business operation
await log_activity(
    action=ActivityAction.UPDATE,
    resource_type="document",
    resource_id=doc_id,
    details={"status": "archived"},
)

# BAD: Too much technical detail
await log_activity(
    action=ActivityAction.UPDATE,
    resource_type="document",
    details={
        "sql_query": "UPDATE documents SET archived_at=...",
        "connection_pool_size": 10,
    },
)
```

### 2. Never Log Sensitive Data

```python
# GOOD: Metadata only
details = {
    "email_changed": True,
    "domain_verified": True,
}

# BAD: Sensitive information
details = {
    "old_password": "SecurePass123!",
    "new_password": "NewPass456!",
    "credit_card": "4532-1488-0343-6467",
}
```

### 3. Use Consistent Resource Types

```python
# Define resource types as constants
RESOURCE_TYPES = {
    "user": "user",
    "organization": "organization",
    "document": "document",
    "membership": "membership",
    "api_key": "api_key",
}

# Use consistently
await log_activity(
    action=ActivityAction.CREATE,
    resource_type=RESOURCE_TYPES["user"],
)
```

### 4. Include Context for Important Operations

```python
# GOOD: Rich context for important operation
await log_activity(
    action=ActivityAction.DELETE,
    resource_type="api_key",
    resource_id=key_id,
    details={
        "key_name": "production-key",
        "age_days": 365,
        "last_used": "2024-01-05T10:30:00Z",
        "reason": "key rotation",
    },
)
```

## Accessing Activity Logs

### In Endpoints

```python
@router.get("/audit-log/{resource_id}")
async def get_resource_audit_log(
    resource_id: UUID,
    session: SessionDep,
    tenant: TenantDep,
) -> list[ActivityLogRead]:
    """Get audit trail for a resource."""
    stmt = select(ActivityLog).where(
        (ActivityLog.resource_id == resource_id)
        & (ActivityLog.organization_id == tenant.organization_id)
    ).order_by(ActivityLog.created_at.desc())

    result = await session.execute(stmt)
    return [ActivityLogRead.model_validate(log) for log in result.scalars().all()]
```

### In Reports

```python
# User activity report
async def user_activity_report(user_id: UUID, days: int = 30):
    """Generate activity report for user."""
    since = datetime.utcnow() - timedelta(days=days)

    stmt = select(ActivityLog).where(
        (ActivityLog.user_id == user_id)
        & (ActivityLog.created_at >= since)
    ).order_by(ActivityLog.created_at)

    results = await session.execute(stmt)
    return results.scalars().all()
```

## Compliance & Retention

### GDPR Compliance

- Activity logs contain user identifiers (PII)
- Implement data retention policies
- Support right-to-be-forgotten (anonymization, not deletion)

```python
async def anonymize_user_activity(user_id: UUID, session: AsyncSession) -> None:
    """Anonymize user activity logs (GDPR compliance)."""
    stmt = select(ActivityLog).where(ActivityLog.user_id == user_id)
    result = await session.execute(stmt)
    logs = result.scalars().all()

    for log in logs:
        log.user_id = None  # Anonymize user reference
        # Keep activity for compliance, but remove user link
        session.add(log)

    await session.commit()
```

### Retention Policy

```python
# Archive logs older than 1 year
async def archive_old_activity_logs(session: AsyncSession) -> None:
    """Archive activity logs older than retention period."""
    retention_days = 365
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    stmt = delete(ActivityLog).where(ActivityLog.created_at < cutoff)
    await session.execute(stmt)
    await session.commit()
```

## Monitoring & Alerts

### Suspicious Activity Detection

```python
# Alert on multiple failed auth attempts
async def check_suspicious_activity(
    organization_id: UUID,
    session: AsyncSession,
) -> None:
    """Detect suspicious patterns in activity logs."""
    # Find failed auth attempts in last hour
    since = datetime.utcnow() - timedelta(hours=1)

    stmt = select(func.count()).select_from(ActivityLog).where(
        (ActivityLog.organization_id == organization_id)
        & (ActivityLog.action == ActivityAction.READ)
        & (ActivityLog.created_at >= since)
        & (ActivityLog.details["error"].astext == "Unauthorized")
    )

    result = await session.execute(stmt)
    count = result.scalar()

    if count > 10:
        # Alert: possible brute force attack
        await send_security_alert(
            f"Suspicious activity in org {organization_id}: {count} failed auth attempts"
        )
```

## See Also

- [Testing External Services](testing_external_services.md) - Testing activity logging with mocks
- [Storage Provider Setup](storage_provider_setup.md) - Activity logging for file operations
