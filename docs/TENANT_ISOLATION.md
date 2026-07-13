# Tenant Isolation Implementation Guide

This document describes the tenant isolation patterns implemented in the fastapi-template project for multi-tenant SaaS applications.

## Overview

Tenant isolation ensures that users can only access data belonging to their organization. This is achieved through:

1. **Middleware-level enforcement** - TenantIsolationMiddleware validates tenant context on every request
2. **Dependency injection** - TenantDep makes tenant context available to endpoints
3. **Service-layer filtering** - Query helpers automatically scope queries to organization_id
4. **Database-level constraints** - Foreign keys and indexes enforce data boundaries

## Architecture

### Defense in Depth

The implementation provides multiple layers of protection:

```
Request → AuthMiddleware → TenantIsolationMiddleware → Endpoint (TenantDep) → Service Layer → Database
   ↓              ↓                    ↓                      ↓                    ↓             ↓
Extract JWT   Validate user   Extract org_id from:     Require tenant    Filter queries   FK constraints
              from token      - JWT claims (primary)   context present   by org_id        prevent orphans
                             - Path params
                             - Query params

                             Verify user ∈ org
```

## Components

### 1. TenantContext Model (`redact_api/core/tenants.py`)

```python
class TenantContext(BaseModel):
    organization_id: UUID  # Current tenant identifier
    user_id: UUID          # Current user (for audit)
```

**Properties:**
- `is_isolated` - Returns True if tenant has valid organization_id and user_id

### 2. TenantIsolationMiddleware

**Responsibilities:**
- Extract organization_id from request (JWT claims, path params, query params)
- Validate user has membership in the organization
- Store tenant context in `request.state.tenant`
- Return 403 if user doesn't belong to organization

**Extraction Priority:**
1. JWT claims (`organization_id` or `org_id` field)
2. Path parameters (e.g., `/orgs/{org_id}/resources`)
3. Query parameters (`org_id=xxx`)

**Public Endpoints (no tenant isolation required):**
- `/health`
- `/ping`
- `/docs`
- `/openapi.json`
- `/redoc`
- `/metrics`

### 3. TenantDep (Dependency)

```python
from redact_api.core.tenants import TenantDep

@router.get("/documents")
async def list_documents(tenant: TenantDep) -> list[DocumentRead]:
    # tenant.organization_id is guaranteed valid
    # User has been verified as member of this organization
    ...
```

Raises 401 if tenant context is not available.

### 4. Query Helpers

#### add_tenant_filter()

Automatically adds WHERE clause to filter by organization_id:

```python
from redact_api.core.tenants import add_tenant_filter

stmt = select(Document)
stmt = add_tenant_filter(stmt, tenant, Document.organization_id)
# Adds: WHERE document.organization_id = tenant.organization_id
```

#### validate_tenant_ownership()

Validates that a resource belongs to the current tenant (for create operations):

```python
from redact_api.core.tenants import validate_tenant_ownership

@router.post("/documents")
async def create_document(
    session: SessionDep,
    tenant: TenantDep,
    payload: DocumentCreate,
) -> DocumentRead:
    # Prevent user from creating documents in other orgs
    await validate_tenant_ownership(session, tenant, payload.organization_id)
    ...
```

## Updated Models

### Document Model

```python
class DocumentBase(SQLModel):
    filename: str
    content_type: str
    file_size: int
    organization_id: UUID  # NEW: Tenant isolation field

class Document(TimestampedTable, DocumentBase, table=True):
    storage_path: str
    storage_url: str

    __table_args__ = (
        sa.Index("ix_document_organization_id", "organization_id"),
    )
```

**Migration Required:**
```sql
ALTER TABLE document
ADD COLUMN organization_id UUID NOT NULL
REFERENCES organization(id) ON DELETE CASCADE;

CREATE INDEX ix_document_organization_id ON document(organization_id);
```

## Updated Services

### Organization Service

Functions now accept optional `user_id` parameter for tenant isolation:

```python
# Without user_id (admin use cases)
org = await get_organization(session, org_id)

# With user_id (tenant-isolated)
org = await get_organization(session, org_id, user_id=current_user.id)
# Returns None if user is not a member
```

**Functions updated:**
- `get_organization(session, organization_id, user_id=None)`
- `list_organizations(session, offset=0, limit=100, user_id=None)`

## Updated Endpoints

### Document Endpoints

All document endpoints now enforce tenant isolation:

```python
@router.post("")
async def upload_document(
    session: SessionDep,
    tenant: TenantDep,  # NEW: Requires tenant context
    file: UploadFile = File(...),
) -> DocumentRead:
    document = Document(
        filename=file.filename,
        content_type=file.content_type,
        file_size=file_size,
        file_data=file_data,
        organization_id=tenant.organization_id,  # NEW: Scoped to tenant
    )
    ...

@router.get("/{document_id}")
async def download_document(
    document_id: UUID,
    session: SessionDep,
    tenant: TenantDep,  # NEW: Requires tenant context
) -> StreamingResponse:
    stmt = select(Document).where(Document.id == document_id)
    stmt = add_tenant_filter(stmt, tenant, Document.organization_id)  # NEW
    ...
```

## Configuration

### Environment Variables

```bash
# Enable/disable tenant isolation (default: true)
ENFORCE_TENANT_ISOLATION=true

# JWT claims must include organization_id
# Your auth provider should populate this field in the token
```

### Main Application Setup

```python
# redact_api/main.py

# 1. Add AuthMiddleware first
from redact_api.core.auth import AuthMiddleware
app.add_middleware(AuthMiddleware)

# 2. Add TenantIsolationMiddleware AFTER AuthMiddleware
from redact_api.core.tenants import TenantIsolationMiddleware
app.add_middleware(TenantIsolationMiddleware)
```

**CRITICAL:** TenantIsolationMiddleware MUST come after AuthMiddleware because it requires authenticated user context.

## Usage Patterns

### Example 1: List Endpoint with Tenant Filtering

```python
from redact_api.core.tenants import TenantDep, add_tenant_filter

@router.get("/documents")
async def list_documents(
    session: SessionDep,
    tenant: TenantDep,
) -> list[DocumentRead]:
    stmt = select(Document)
    stmt = add_tenant_filter(stmt, tenant, Document.organization_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

### Example 2: Create Endpoint with Tenant Scoping

```python
from redact_api.core.tenants import TenantDep

@router.post("/documents")
async def create_document(
    session: SessionDep,
    tenant: TenantDep,
    payload: DocumentCreate,
) -> DocumentRead:
    # Automatically scope to tenant's organization
    document = Document(
        **payload.model_dump(),
        organization_id=tenant.organization_id,
    )
    session.add(document)
    await session.commit()
    return DocumentRead.model_validate(document)
```

### Example 3: Update/Delete with Tenant Verification

```python
from redact_api.core.tenants import TenantDep, add_tenant_filter

@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: UUID,
    session: SessionDep,
    tenant: TenantDep,
) -> None:
    # Query is automatically scoped to tenant
    stmt = select(Document).where(Document.id == document_id)
    stmt = add_tenant_filter(stmt, tenant, Document.organization_id)

    result = await session.execute(stmt)
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(404, "Document not found")

    await session.delete(document)
    await session.commit()
```

## Security Guarantees

### What This Implementation Prevents

1. **Cross-tenant data access** - User A cannot access Organization B's data
2. **Organization spoofing** - User cannot specify different org_id in requests
3. **Membership bypass** - User must be verified member of organization
4. **Accidental data leaks** - Service layer queries automatically filtered

### What You Still Need to Implement

1. **Resource ownership** - Fine-grained permissions (user owns specific documents)
2. **Admin bypass** - Global admin endpoints that transcend tenant boundaries
3. **Audit logging** - Track who accessed what (use activity_logging module)

## Role-Based Access Control (RBAC)

In addition to tenant isolation, this template implements role-based permissions within organizations.

### Three-Tier Role Model

The template provides three hierarchical roles:

| Role | Permissions | Use Case |
|------|-------------|----------|
| **OWNER** | Full control: delete org, change roles, manage members/settings | Organization creator, primary stakeholder |
| **ADMIN** | Manage members and update settings (cannot delete org or change roles) | Team leads, department managers |
| **MEMBER** | Use organization resources (read-only on org settings) | Regular users, contributors |

**Role Hierarchy:** OWNER > ADMIN > MEMBER

An OWNER can perform all ADMIN operations, and an ADMIN can perform all MEMBER operations.

### Implementation

#### 1. MembershipRole Enum

```python
from redact_api.models.membership import MembershipRole

class MembershipRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
```

#### 2. Membership Model

Each membership now includes a `role` field:

```python
class Membership(TimestampedTable, MembershipBase, table=True):
    user_id: UUID
    organization_id: UUID
    role: MembershipRole = Field(default=MembershipRole.MEMBER)
```

**Default behavior:** New members default to MEMBER role. First member of an organization should be assigned OWNER.

#### 3. Permission Dependencies

```python
from redact_api.core.permissions import RequireAdmin, RequireOwner

# Require ADMIN role (or higher)
@router.patch("/organizations/{organization_id}")
async def update_org(
    organization_id: UUID,
    payload: OrganizationUpdate,
    session: SessionDep,
    role_check: RequireAdmin,  # Enforces ADMIN or OWNER
) -> OrganizationRead:
    ...

# Require OWNER role
@router.delete("/organizations/{organization_id}")
async def delete_org(
    organization_id: UUID,
    session: SessionDep,
    role_check: RequireOwner,  # Enforces OWNER only
) -> None:
    ...
```

### Protected Operations

#### Organization Management

| Endpoint | Required Role | Description |
|----------|---------------|-------------|
| `DELETE /organizations/{id}` | OWNER | Delete organization and all data |
| `PATCH /organizations/{id}` | ADMIN | Update organization settings |
| `GET /organizations/{id}` | MEMBER | View organization details |

#### Membership Management

| Endpoint | Required Role | Description |
|----------|---------------|-------------|
| `POST /memberships` | ADMIN | Add new members |
| `DELETE /memberships/{id}` | ADMIN | Remove members |
| `PATCH /memberships/{id}` | OWNER | Change member roles |
| `GET /memberships` | MEMBER | List organization members |

### Role Change Rules

1. **Only OWNER can change roles** - Prevents privilege escalation
2. **Users cannot promote themselves** - Should be enforced at application level
3. **Hierarchy enforced** - OWNER has all ADMIN permissions, ADMIN has all MEMBER permissions
4. **First member is OWNER** - Migration automatically sets earliest member to OWNER

### Role Transition Constraints

**Self-Role Changes**: Users cannot change their own role, regardless of their current role. This prevents:
- Accidental self-demotion
- Privilege escalation attempts
- Organizational deadlock (e.g., sole OWNER demoting themselves)

**Last Owner Protection**: Currently not enforced at the application level. Organizations CAN have zero owners if:
- The only owner changes another user's role to owner, then leaves
- An admin is promoted to owner, then demotes the original owner

**Future Enhancement**: Consider adding validation to prevent demoting the last owner of an organization. This would ensure every organization always has at least one owner for administrative purposes.

### Usage Example

```python
from redact_api.core.permissions import RequireAdmin, RequireOwner
from redact_api.core.tenants import TenantDep

@router.post("/memberships")
async def add_member(
    payload: MembershipCreate,
    session: SessionDep,
    tenant: TenantDep,
    role_check: RequireAdmin,  # User must be ADMIN or OWNER
) -> MembershipRead:
    # Tenant isolation ensures user is in this organization
    # Role check ensures user has ADMIN+ permissions
    membership = await create_membership(session, payload)
    return MembershipRead.model_validate(membership)
```

### Security Guarantees

**RBAC provides:**
1. **Destructive operations require OWNER** - Prevents accidental data loss
2. **Administrative actions require ADMIN** - Separates management from usage
3. **Explicit permission checks** - No implicit permissions
4. **Role hierarchy** - Higher roles inherit lower role permissions

**What's NOT included (out of scope):**
1. **Custom roles** - Only three fixed roles (OWNER, ADMIN, MEMBER)
2. **Resource-level permissions** - Roles are organization-wide, not per-resource
3. **Permission delegation** - Users cannot delegate their permissions
4. **Time-limited roles** - Roles are permanent until changed by OWNER

## Testing Tenant Isolation

### Unit Tests

```python
async def test_document_isolation(session: AsyncSession):
    # Create two orgs
    org1 = Organization(name="Org 1")
    org2 = Organization(name="Org 2")
    session.add_all([org1, org2])
    await session.commit()

    # Create document in org1
    doc = Document(
        filename="test.pdf",
        content_type="application/pdf",
        file_size=1024,
        organization_id=org1.id,
        storage_path="/path",
        storage_url="http://example.com",
    )
    session.add(doc)
    await session.commit()

    # Verify org2 tenant cannot access doc
    tenant_org2 = TenantContext(organization_id=org2.id, user_id=uuid4())
    stmt = select(Document).where(Document.id == doc.id)
    stmt = add_tenant_filter(stmt, tenant_org2, Document.organization_id)

    result = await session.execute(stmt)
    assert result.scalar_one_or_none() is None  # Should not be accessible
```

### Integration Tests

```python
async def test_middleware_prevents_cross_tenant_access(client: AsyncClient):
    # Create user in org1
    user_org1_token = create_jwt(user_id=user1.id, organization_id=org1.id)

    # Try to access org2's document
    response = await client.get(
        f"/documents/{org2_document_id}",
        headers={"Authorization": f"Bearer {user_org1_token}"},
    )

    # Should return 404 (not 403, to avoid leaking existence)
    assert response.status_code == 404
```

## Migration Guide

### Existing Projects

1. **Add organization_id to all tenant-scoped tables**
   ```sql
   ALTER TABLE your_table
   ADD COLUMN organization_id UUID NOT NULL
   REFERENCES organization(id) ON DELETE CASCADE;

   CREATE INDEX ix_your_table_organization_id ON your_table(organization_id);
   ```

2. **Update models** to include organization_id field

3. **Add TenantDep to all endpoints** that access tenant-scoped data

4. **Update service layer** to use `add_tenant_filter()`

5. **Enable middleware** in main.py

6. **Test thoroughly** with multiple tenants

### New Projects

Follow the patterns shown in:
- `redact_api/models/document.py` - Model with organization_id
- `redact_api/api/documents.py` - Endpoints using TenantDep
- `redact_api/services/organization_service.py` - Services with user_id filtering

## Troubleshooting

### "Tenant context required but not available"

**Cause:** Endpoint requires TenantDep but middleware hasn't set tenant context.

**Solutions:**
1. Ensure TenantIsolationMiddleware is enabled in main.py
2. Verify JWT token includes `organization_id` or `org_id` claim
3. Check user is member of the organization (query Membership table)

### "User does not have access to this organization"

**Cause:** User attempting to access organization they're not a member of.

**Solutions:**
1. Verify Membership record exists for user and organization
2. Check JWT token has correct organization_id claim
3. Ensure organization_id in request matches user's memberships

### Query returns empty results despite data existing

**Cause:** Tenant filter is excluding data (working as intended).

**Solutions:**
1. Verify organization_id on records matches tenant.organization_id
2. Check if records were created with correct organization_id
3. For debugging, temporarily remove tenant filter to confirm data exists

## Performance Considerations

### Database Indexes

Ensure all tenant-scoped tables have indexes on organization_id:

```sql
CREATE INDEX ix_table_name_organization_id ON table_name(organization_id);
```

### Query Patterns

**Good (uses index):**
```python
# Filter by organization_id first
stmt = select(Document).where(Document.organization_id == tenant.organization_id)
stmt = stmt.where(Document.filename.like("%test%"))
```

**Bad (slow):**
```python
# Filter by other fields first, then organization_id
stmt = select(Document).where(Document.filename.like("%test%"))
stmt = stmt.where(Document.organization_id == tenant.organization_id)
```

### Caching

Consider caching membership validation results:

```python
# In production, cache this query for 5-10 minutes
# Key: f"membership:{user_id}:{organization_id}"
has_access = await _validate_user_org_access(session, user_id, org_id)
```

## References

- [OWASP: Insecure Direct Object References (IDOR)](https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/05-Authorization_Testing/04-Testing_for_Insecure_Direct_Object_References)
- [Multi-Tenancy Architecture Patterns](https://docs.microsoft.com/en-us/azure/architecture/guide/multitenant/overview)
- [FastAPI Security Best Practices](https://fastapi.tiangolo.com/tutorial/security/)

## License

This is free and unencumbered software released into the public domain.

For more information, please refer to <http://unlicense.org/>
