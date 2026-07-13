# Deployment Variants: Single-Tenant vs Multi-Tenant

Design guide for choosing and implementing deployment variants of the FastAPI template.

## Overview

The template is built for **multi-tenant deployments by default**, but can be adapted for single-tenant deployments. Choose the variant that matches your deployment strategy.

## Comparison Matrix

| Aspect | Single-Tenant | Multi-Tenant |
|--------|---------------|--------------|
| **Deployment** | One instance per customer | All customers share instance |
| **Data Isolation** | Automatic (separate databases) | Explicit (tenant ID filtering) |
| **Cost** | Higher (per-customer infra) | Lower (shared resources) |
| **Isolation** | Perfect | Via code (must be enforced) |
| **Compliance** | Easy (each customer separate) | Complex (shared infra) |
| **Scalability** | Per-customer | Across all customers |
| **Customization** | Per-customer code possible | Limited (shared codebase) |

## Multi-Tenant (Default)

The template is configured for multi-tenant by default. All customers use the same codebase and database, but data is isolated by `organization_id`.

### Architecture

```
┌─────────────────────────────────────────┐
│     FastAPI Application Instance        │
│  (All organizations share one instance)  │
└─────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────┐
│     PostgreSQL Database (Single)        │
│  ┌─────────┬─────────┬─────────┐        │
│  │  Org A  │  Org B  │  Org C  │  ...   │
│  │  Data   │  Data   │  Data   │        │
│  └─────────┴─────────┴─────────┘        │
└─────────────────────────────────────────┘
```

### Tenant Isolation Mechanism

All queries are scoped to the current tenant's `organization_id`:

```python
# TenantDep provides organization_id from JWT/path/query
@router.get("/documents")
async def list_documents(
    session: SessionDep,
    tenant: TenantDep,  # Current tenant context
) -> list[DocumentRead]:
    # All queries automatically scoped to tenant.organization_id
    stmt = select(Document).where(
        Document.organization_id == tenant.organization_id
    )
    return results
```

### Configuration

Multi-tenant is enabled by default:

```python
# .env
ENFORCE_TENANT_ISOLATION=true  # Require tenant context

# Settings in core/config.py
enforce_tenant_isolation: bool = Field(
    default=True,
    description="Enforce tenant isolation (for multi-tenant)",
)
```

### Advantages

✅ **Cost Efficient**: Shared infrastructure for all customers
✅ **Easy Deployment**: Deploy once, all customers benefit
✅ **Scalable**: Add customers without new instances
✅ **Resource Efficient**: Shared connection pools, caches

### Challenges

❌ **Isolation Risk**: Bugs in query logic can leak data
❌ **Compliance**: GDPR/compliance harder with shared infra
❌ **Debugging**: Hard to reproduce tenant-specific issues
❌ **Customization**: All customers get same features/performance

### Best Practices

```python
# 1. Always filter by tenant_id in queries
# GOOD
stmt = select(Document).where(
    (Document.organization_id == tenant.organization_id)
    & (Document.archived_at.is_(None))
)

# BAD - Missing tenant filter!
stmt = select(Document).where(Document.archived_at.is_(None))

# 2. Use helper functions to enforce filtering
async def get_documents_for_tenant(
    session: AsyncSession,
    tenant: TenantContext,
) -> list[Document]:
    """Ensures tenant filtering is applied."""
    stmt = select(Document).where(
        Document.organization_id == tenant.organization_id
    )
    return results

# 3. Audit all tenant access
@router.get("/documents/{doc_id}")
async def get_document(
    doc_id: UUID,
    session: SessionDep,
    tenant: TenantDep,
) -> DocumentRead:
    """Tenant-scoped document access."""
    document = await session.get(Document, doc_id)

    # Verify tenant can access
    if document.organization_id != tenant.organization_id:
        raise HTTPException(status_code=403, detail="Not your document")

    return DocumentRead.model_validate(document)

# 4. Test tenant isolation
def test_user_cannot_access_other_tenant():
    """Ensure users cannot access other orgs' data."""
    # Create documents in org A and org B
    doc_a = await create_document(org_a, "doc.pdf")
    doc_b = await create_document(org_b, "doc.pdf")

    # User from org A tries to access org B's document
    response = await client.get(
        f"/documents/{doc_b.id}",
        headers=get_auth_headers(org_a_user),
    )

    # Should fail with 403 or 404
    assert response.status_code in (403, 404)
```

## Single-Tenant (Alternative)

Deploy one instance per customer with completely separate databases.

### Architecture

```
Customer A                Customer B
┌──────────────────┐      ┌──────────────────┐
│  FastAPI App A   │      │  FastAPI App B   │
└────────┬─────────┘      └─────────┬────────┘
         ↓                          ↓
┌──────────────────┐      ┌──────────────────┐
│ PostgreSQL DB A  │      │ PostgreSQL DB B  │
│ (Private)        │      │ (Private)        │
└──────────────────┘      └──────────────────┘
```

### Implementation

#### 1. Disable Tenant Isolation

```python
# .env
ENFORCE_TENANT_ISOLATION=false  # Each instance is single-tenant

# Or handle in middleware
if not settings.is_multi_tenant:
    # Skip tenant context requirement
    request.state.tenant = TenantContext(
        organization_id=settings.default_organization_id,
        user_id=current_user.id,
    )
```

#### 2. Remove Tenant Filtering from Queries

```python
# Single-tenant: no organization_id filtering needed
@router.get("/documents")
async def list_documents(session: SessionDep) -> list[DocumentRead]:
    stmt = select(Document)  # No tenant filter
    return results
```

#### 3. Simplify Auth

```python
# Single-tenant: no organization selection in JWT
# Just authenticate user, don't need org context
@router.post("/login")
async def login(credentials: Credentials) -> TokenResponse:
    user = await verify_user(credentials)
    token = create_token(
        user_id=user.id,
        # No organization_id in token
    )
    return TokenResponse(access_token=token)
```

#### 4. Deployment Configuration

Use environment variables to configure per-deployment:

```python
class Settings(BaseSettings):
    # Deployment mode
    deployment_mode: str = Field(
        default="multi_tenant",  # or "single_tenant"
        alias="DEPLOYMENT_MODE",
    )

    # Single-tenant only
    default_organization_id: UUID | None = Field(
        default=None,
        alias="DEFAULT_ORGANIZATION_ID",
    )

    # Multi-tenant only
    enforce_tenant_isolation: bool = Field(
        default=True,
        alias="ENFORCE_TENANT_ISOLATION",
    )

    @property
    def is_multi_tenant(self) -> bool:
        """Check if running in multi-tenant mode."""
        return self.deployment_mode == "multi_tenant"

    @property
    def is_single_tenant(self) -> bool:
        """Check if running in single-tenant mode."""
        return self.deployment_mode == "single_tenant"
```

#### 5. Data Isolation

Single-tenant can use separate databases for better isolation:

```python
# Deployment-specific database configuration
class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql://...",
        alias="DATABASE_URL",
    )

    # Single-tenant option: per-customer database
    customer_database_url: str | None = Field(
        default=None,
        alias="CUSTOMER_DATABASE_URL",
    )

    @property
    def active_database_url(self) -> str:
        """Get database URL for this deployment."""
        if self.is_single_tenant and self.customer_database_url:
            return self.customer_database_url
        return self.database_url
```

### Advantages

✅ **Perfect Isolation**: Separate databases = no data leakage risk
✅ **Compliance**: Each customer has independent infrastructure
✅ **Customization**: Per-customer code/schema possible
✅ **Debugging**: Easy to debug customer-specific issues
✅ **Performance**: No noisy neighbor problem

### Challenges

❌ **Cost**: Multiple instances and databases
❌ **Operational Complexity**: Manage many deployments
❌ **Scaling**: New instance per customer
❌ **Deployment**: More complex CI/CD

## Hybrid Approach

Some deployments use hybrid models:

### Multi-Tenant for SMB, Single-Tenant for Enterprise

```python
if customer.tier == "enterprise":
    # Deploy on separate infrastructure
    deploy_single_tenant_instance(customer)
else:
    # Deploy on shared multi-tenant infrastructure
    add_tenant_to_shared_instance(customer)
```

## Migration Path

### Multi-Tenant → Single-Tenant

When growing, enterprise customers may need dedicated deployments:

```python
async def migrate_customer_to_single_tenant(
    customer_id: UUID,
    session: AsyncSession,
) -> None:
    """Migrate customer from shared to dedicated deployment."""
    # 1. Export customer data
    customer_data = await export_customer_data(customer_id)

    # 2. Create dedicated database
    dedicated_db = await create_customer_database(customer_id)

    # 3. Import data
    await import_data_to_database(dedicated_db, customer_data)

    # 4. Update DNS/routing
    await update_customer_endpoint(customer_id, dedicated_url)

    # 5. Verify
    await verify_migration(customer_id)

    # 6. Archive shared tenant data (after verification)
    await archive_old_data(customer_id)
```

## Decision Framework

Choose deployment variant based on:

### Use Multi-Tenant If...

- ✅ Targeting SMB/mid-market customers
- ✅ Want lowest cost of ownership
- ✅ Don't have strict data isolation requirements
- ✅ Can ensure robust query filtering
- ✅ Want rapid customer onboarding
- ✅ Customers comfortable with shared infra

### Use Single-Tenant If...

- ✅ Targeting enterprise customers
- ✅ Need strict data isolation/compliance
- ✅ Can afford higher operational costs
- ✅ Need per-customer customization
- ✅ Want to support customer-managed deployments
- ✅ Need high performance per customer

### Use Hybrid If...

- ✅ Serving both SMB and enterprise
- ✅ Want flexibility for different customer tiers
- ✅ Can manage multi-tier infrastructure
- ✅ Want to upgrade customers over time

## Configuration Examples

### Multi-Tenant Configuration

```bash
# .env for multi-tenant SaaS
DEPLOYMENT_MODE=multi_tenant
ENFORCE_TENANT_ISOLATION=true
DATABASE_URL=postgresql://shared-db.example.com:5432/saas
STORAGE_PROVIDER=aws_s3
```

### Single-Tenant Configuration

```bash
# .env for customer-specific deployment
DEPLOYMENT_MODE=single_tenant
DEFAULT_ORGANIZATION_ID=550e8400-e29b-41d4-a716-446655440000
DATABASE_URL=postgresql://customer-db.example.com:5432/customer
STORAGE_PROVIDER=azure
STORAGE_AZURE_CONTAINER=customer-bucket
```

## Testing Variants

### Multi-Tenant Tests

```python
def test_multi_tenant_isolation():
    """Ensure tenants cannot access each other's data."""
    # Create data for org A and B
    doc_a = create_document(org_a, "secret.pdf")
    doc_b = create_document(org_b, "secret.pdf")

    # User A tries to access B's document
    with tenant_context(org_a):
        # Should not find org B's document
        with raises(NotFound):
            get_document(doc_b.id)
```

### Single-Tenant Tests

```python
def test_single_tenant_no_org_filtering():
    """Ensure single-tenant doesn't require org filtering."""
    # Create documents
    doc = create_document("file.pdf")

    # Should be accessible without org context
    retrieved = get_document(doc.id)
    assert retrieved.id == doc.id
```

## See Also

- [Activity Logging](activity_logging.md) - Audit trails for compliance
- [Resilience Patterns](resilience_patterns.md) - Handle service outages
- [Testing External Services](testing_external_services.md) - Test deployment variants
