# Configuration Guide

Complete reference for all environment variables and feature configuration options.

---

## Environment Variables Quick Reference

| Variable | Type | Default | Required | Purpose |
|----------|------|---------|----------|---------|
| `SECRET_KEY` | str | (none) | ✅ Prod only | JWT signing key, min 32 chars |
| `DEBUG` | bool | true | ❌ | Enable debug mode (NEVER in production) |
| `DATABASE_URL` | str | (required) | ✅ | PostgreSQL async connection URL |
| `ENVIRONMENT` | str | development | ❌ | Environment name (development, staging, production) |
| `LOG_LEVEL` | str | info | ❌ | Logging level (debug, info, warning, error, critical) |
| `LOG_FORMAT` | str | json | ❌ | Log output format (json or text) |
| `STRUCTURED_LOGGING` | bool | true | ❌ | Include request context in logs |
| `AUTH_PROVIDER_TYPE` | str | none | ❌ | Auth provider (none, ory, auth0, keycloak, cognito) |
| `ENFORCE_TENANT_ISOLATION` | bool | true | ❌ | Enable multi-tenant isolation |
| `ACTIVITY_LOGGING_ENABLED` | bool | true | ❌ | Enable audit trail logging |
| `ACTIVITY_LOG_RETENTION_DAYS` | int | 90 | ❌ | Archive logs older than N days |
| `METRICS_ENABLED` | bool | true | ❌ | Enable Prometheus metrics |
| `STORAGE_PROVIDER` | str | local | ❌ | Storage backend (local, s3, azure, gcs) |
| `STORAGE_LOCAL_PATH` | str | ./uploads | ❌ | Local storage directory (if local) |
| `MAX_FILE_SIZE_BYTES` | int | 52428800 | ❌ | Maximum file upload size (50MB default) |
| `CORS_ORIGINS` | str | ["http://localhost:3000"] | ❌ | CORS allowed origins (JSON array) |

---

## Authentication Configuration

Choose one authentication provider or disable authentication for local development.

### Option 1: No Authentication (Development Only)

For local development without any authentication:

```bash
# .env
AUTH_PROVIDER_TYPE=none
# Don't uncomment AuthMiddleware in redact_api/main.py
```

**Behavior**:
- All endpoints accessible without tokens
- Requests have no user context
- Perfect for local development and testing

**When to use**:
- Local development
- Integration testing
- Prototyping

---

### Option 2: Ory (Recommended for Multi-Tenant SaaS)

Ory is an open-source identity and access management platform, perfect for multi-tenant applications.

**Prerequisites**:
1. Create Ory account at https://console.ory.sh
2. Create a new Ory project
3. Get your tenant ID (appears in console URLs)

**Configuration**:

```bash
# .env
AUTH_PROVIDER_TYPE=ory
ORY_TENANT=your-tenant-slug
ORY_JWKS_URL=https://your-tenant.ory.sh/.well-known/jwks.json
ORY_INTROSPECTION_URL=https://your-tenant.ory.sh/admin/oauth2/introspect  # Optional
```

**Enable middleware** in `redact_api/main.py`:

```python
app.add_middleware(AuthMiddleware)
```

**Test integration**:

```bash
# Login creates JWT token
curl -X POST https://your-tenant.ory.sh/oauth2/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=...&client_secret=...&grant_type=client_credentials"

# Use token to call your API
curl http://localhost:8000/users \
  -H "Authorization: Bearer $TOKEN"
```

For detailed setup, see the [Ory documentation](https://www.ory.sh/docs/).

---

### Option 3: Auth0

Auth0 is a cloud-based identity provider with easy setup and rich features.

**Prerequisites**:
1. Create Auth0 account at https://auth0.com
2. Create a new Auth0 application
3. Get your domain (e.g., `your-domain.auth0.com`)

**Configuration**:

```bash
# .env
AUTH_PROVIDER_TYPE=auth0
AUTH0_DOMAIN=your-domain.auth0.com
AUTH0_JWKS_URL=https://your-domain.auth0.com/.well-known/jwks.json
AUTH0_AUDIENCE=your-api-identifier  # Optional: if using audience claims
```

**Enable middleware** in `redact_api/main.py`:

```python
app.add_middleware(AuthMiddleware)
```

**Get JWKS URL**:

```bash
# Visit in browser:
https://your-domain.auth0.com/.well-known/openid-configuration

# The jwks_uri field gives you the JWKS URL
```

**Test integration**:

```bash
# Get token via Auth0 (requires configured client)
# Then use token with your API:
curl http://localhost:8000/users \
  -H "Authorization: Bearer $TOKEN"
```

For detailed setup, see the [Auth0 documentation](https://auth0.com/docs/).

---

### Option 4: Keycloak

Keycloak is an open-source identity provider suitable for self-hosted deployments.

**Prerequisites**:
1. Deploy Keycloak (docker, helm, or on-premises)
2. Create a realm
3. Create a client application
4. Get your realm URL (e.g., `https://keycloak.example.com/realms/myrealm`)

**Configuration**:

```bash
# .env
AUTH_PROVIDER_TYPE=keycloak
KEYCLOAK_REALM_URL=https://keycloak.example.com/realms/myrealm
KEYCLOAK_JWKS_URL=https://keycloak.example.com/realms/myrealm/protocol/openid-connect/certs
```

**Enable middleware** in `redact_api/main.py`:

```python
app.add_middleware(AuthMiddleware)
```

**Start Keycloak locally** (for testing):

```bash
docker run -d \
  -e KEYCLOAK_ADMIN=admin \
  -e KEYCLOAK_ADMIN_PASSWORD=admin \
  -p 8080:8080 \
  quay.io/keycloak/keycloak:latest \
  start-dev
```

Then visit http://localhost:8080 and follow setup wizard.

For detailed setup, see the [Keycloak documentation](https://www.keycloak.org/documentation).

---

### Option 5: AWS Cognito

AWS Cognito is managed by Amazon, ideal if you're already in AWS ecosystem.

**Prerequisites**:
1. Create AWS Cognito User Pool in AWS Console
2. Create an App Client
3. Get your user pool ID and region

**Configuration**:

```bash
# .env
AUTH_PROVIDER_TYPE=cognito
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_xxxxxxxxx  # From AWS Console
COGNITO_JWKS_URL=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_xxxxxxxxx/.well-known/jwks.json
```

**Enable middleware** in `redact_api/main.py`:

```python
app.add_middleware(AuthMiddleware)
```

**Get JWKS URL** (can also construct from user pool ID):

```bash
# Format: https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json
# Example: https://cognito-idp.us-east-1.amazonaws.com/us-east-1_abc123xyz/.well-known/jwks.json
```

For detailed setup, see the [AWS Cognito documentation](https://docs.aws.amazon.com/cognito/).

---

## Tenant Isolation Configuration

Control whether your application supports single-tenant or multi-tenant isolation.

### Single-Tenant Application (Default)

For applications with a single organization:

```bash
# .env
ENFORCE_TENANT_ISOLATION=false
# Don't uncomment TenantIsolationMiddleware in redact_api/main.py
```

**When to use**:
- Single company/organization
- Team collaboration tool with one workspace
- SaaS with only your team as users

---

### Multi-Tenant Application (SaaS)

For SaaS with multiple independent organizations:

```bash
# .env
ENFORCE_TENANT_ISOLATION=true
# Uncomment TenantIsolationMiddleware in redact_api/main.py (AFTER AuthMiddleware!)
```

**What this enables**:
- Each user belongs to one or more organizations
- User A cannot see Organization B's data
- Queries automatically filtered by organization_id
- Documents, users, memberships scoped to tenant

**Middleware order** (critical!):

```python
# In redact_api/main.py, add in this order:

# 1. Authentication FIRST
app.add_middleware(AuthMiddleware)

# 2. Tenant Isolation SECOND
# (relies on user context from AuthMiddleware)
app.add_middleware(TenantIsolationMiddleware)
```

**For details**, see [docs/TENANT_ISOLATION.md](docs/TENANT_ISOLATION.md).

---

## Storage Configuration

Choose where to store uploaded files.

### Local Storage (Development)

For local development and testing:

```bash
# .env
STORAGE_PROVIDER=local
STORAGE_LOCAL_PATH=./uploads
MAX_FILE_SIZE_BYTES=52428800  # 50MB
```

**File structure**:
```
uploads/
└── {organization_id}/
    └── {document_id}
```

**Pros**: Zero setup, works immediately
**Cons**: Not suitable for production, doesn't scale

---

### AWS S3 (Production)

For production deployments on AWS:

**Prerequisites**:
1. S3 bucket created
2. IAM user with S3 permissions or role attached to EC2/Lambda
3. Access key and secret (if not using IAM role)

**Configuration**:

```bash
# .env
STORAGE_PROVIDER=s3
STORAGE_AWS_BUCKET=my-app-uploads
STORAGE_AWS_REGION=us-east-1
STORAGE_AWS_ACCESS_KEY_ID=AKIA...
STORAGE_AWS_SECRET_ACCESS_KEY=...
MAX_FILE_SIZE_BYTES=52428800
```

**Create S3 bucket** (CLI):

```bash
aws s3 mb s3://my-app-uploads --region us-east-1
```

**Create IAM user with S3 access** (CLI):

```bash
# Create user
aws iam create-user --user-name app-s3-user

# Attach policy
aws iam attach-user-policy \
  --user-name app-s3-user \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

# Create access key
aws iam create-access-key --user-name app-s3-user
```

**File path format**:
```
s3://my-app-uploads/{organization_id}/{document_id}
```

---

### Azure Blob Storage (Production)

For production deployments on Azure:

**Prerequisites**:
1. Azure Storage Account created
2. Container created
3. Connection string or account key

**Configuration**:

```bash
# .env
STORAGE_PROVIDER=azure
STORAGE_AZURE_CONTAINER=uploads
STORAGE_AZURE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=mystorageaccount;AccountKey=...;EndpointSuffix=core.windows.net
MAX_FILE_SIZE_BYTES=52428800
```

**Get connection string** (Azure Portal):
1. Go to Storage Account → Access Keys
2. Copy "Connection string" field

**File path format**:
```
azure://uploads/{organization_id}/{document_id}
```

---

### Google Cloud Storage (Production)

For production deployments on GCP:

**Prerequisites**:
1. GCS bucket created
2. Service account with Storage permissions
3. Service account key file (JSON)

**Configuration**:

```bash
# .env
STORAGE_PROVIDER=gcs
STORAGE_GCS_BUCKET=my-app-uploads
STORAGE_GCS_PROJECT_ID=my-gcp-project
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
MAX_FILE_SIZE_BYTES=52428800
```

**Create service account** (gcloud CLI):

```bash
# Create service account
gcloud iam service-accounts create app-storage \
  --display-name="App Storage Service"

# Create key
gcloud iam service-accounts keys create service-account-key.json \
  --iam-account=app-storage@PROJECT_ID.iam.gserviceaccount.com

# Grant Storage permissions
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member=serviceAccount:app-storage@PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/storage.admin
```

**File path format**:
```
gs://my-app-uploads/{organization_id}/{document_id}
```

---

## Activity Logging Configuration

Control audit trail and activity log retention.

```bash
# .env
ACTIVITY_LOGGING_ENABLED=true              # Enable/disable
ACTIVITY_LOG_RETENTION_DAYS=90             # Archive after N days
```

**What gets logged**:
- User creation, updates, deletions
- Organization creation, updates, deletions
- Document uploads, downloads, deletions
- All changes to relationships and metadata

**Fields logged**:
- Timestamp (ISO 8601)
- User ID and email (who performed action)
- Action type (CREATE, READ, UPDATE, DELETE)
- Resource type and ID
- Changes (before/after for UPDATE)
- Request ID (for tracing)

**Disable logging** (not recommended):

```bash
ACTIVITY_LOGGING_ENABLED=false
```

For details, see [docs/activity_logging.md](docs/activity_logging.md).

---

## Observability Configuration

Enable monitoring and debugging features.

```bash
# .env
METRICS_ENABLED=true                       # Prometheus metrics
LOG_LEVEL=info                             # Logging verbosity
LOG_FORMAT=json                            # Output format
STRUCTURED_LOGGING=true                    # Include request context
```

**Metrics endpoint**:
```bash
curl http://localhost:8000/metrics
```

**Metrics include**:
- `users_created_total` - Total users created
- `organizations_created_total` - Total organizations
- `documents_uploaded_total` - File uploads
- `http_requests_duration_seconds` - Request latency
- `db_query_duration_seconds` - Query duration

**Logging levels**:
- `debug` - All messages (development only)
- `info` - General information (default)
- `warning` - Warning messages
- `error` - Error messages only
- `critical` - Critical issues only

---

## CORS Configuration

Control which domains can access your API.

```bash
# .env
CORS_ORIGINS=["http://localhost:3000", "https://app.example.com"]
```

**Format**: JSON array of URLs

**Default**: Allows `http://localhost:3000` (for local frontend development)

---

## Example Configurations

### Development Setup

```bash
# .env
SECRET_KEY=dev-key-do-not-use-in-production
DEBUG=true
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/myapp
ENVIRONMENT=development
AUTH_PROVIDER_TYPE=none
ENFORCE_TENANT_ISOLATION=false
STORAGE_PROVIDER=local
STORAGE_LOCAL_PATH=./uploads
ACTIVITY_LOGGING_ENABLED=true
METRICS_ENABLED=true
LOG_LEVEL=debug
CORS_ORIGINS=["http://localhost:3000", "http://localhost:8000"]
```

### Production Setup (Auth0 + S3)

```bash
# .env
SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(32))">
DEBUG=false
DATABASE_URL=postgresql+asyncpg://user:password@prod-db.example.com:5432/app_prod
ENVIRONMENT=production
AUTH_PROVIDER_TYPE=auth0
AUTH0_DOMAIN=your-domain.auth0.com
AUTH0_JWKS_URL=https://your-domain.auth0.com/.well-known/jwks.json
ENFORCE_TENANT_ISOLATION=true
STORAGE_PROVIDER=s3
STORAGE_AWS_BUCKET=app-uploads-prod
STORAGE_AWS_REGION=us-east-1
ACTIVITY_LOGGING_ENABLED=true
METRICS_ENABLED=true
LOG_LEVEL=info
CORS_ORIGINS=["https://app.example.com", "https://admin.example.com"]
```

### SaaS Setup (Ory + Multi-Tenant)

```bash
# .env
SECRET_KEY=<generate random 32+ chars>
DEBUG=false
DATABASE_URL=postgresql+asyncpg://...
ENVIRONMENT=production
AUTH_PROVIDER_TYPE=ory
ORY_TENANT=your-tenant
ORY_JWKS_URL=https://your-tenant.ory.sh/.well-known/jwks.json
ENFORCE_TENANT_ISOLATION=true  # CRITICAL for SaaS
STORAGE_PROVIDER=s3
STORAGE_AWS_BUCKET=saas-uploads
ACTIVITY_LOGGING_ENABLED=true  # For compliance
METRICS_ENABLED=true
LOG_LEVEL=info
```

---

## Validation Checklist

**Before deploying to production**, verify:

- [ ] `SECRET_KEY` is set to a random 32+ character value
- [ ] `SECRET_KEY` is NOT committed to git
- [ ] `DEBUG=false`
- [ ] `DATABASE_URL` points to production database (not local)
- [ ] `AUTH_PROVIDER_TYPE` is configured (not `none`)
- [ ] Auth provider credentials are set (JWKS URL, etc.)
- [ ] `ENFORCE_TENANT_ISOLATION=true` (if multi-tenant)
- [ ] `STORAGE_PROVIDER` is configured (S3, Azure, or GCS - not local)
- [ ] All storage credentials are set
- [ ] `.env` file is in `.gitignore` (never commit)
- [ ] `ACTIVITY_LOGGING_ENABLED=true` (for compliance)
- [ ] `METRICS_ENABLED=true` (for monitoring)
- [ ] `LOG_LEVEL=info` (not debug)
- [ ] `ENVIRONMENT=production`
- [ ] All tests pass: `uv run pytest tests/`
- [ ] Linting passes: `uv run ruff check .`
- [ ] Type checking passes: `uv run mypy .`
- [ ] CORS_ORIGINS includes your frontend domains only

---

## Environment Variable Security

**CRITICAL**: Never commit `.env` file to git!

```bash
# .gitignore
.env
.env.local
.env.*.local
```

**Secure practices**:
1. Generate `SECRET_KEY` with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Use different keys for dev, staging, production
3. Rotate credentials periodically
4. Use secrets management (AWS Secrets Manager, Azure Key Vault, etc.) in production
5. Use IAM roles instead of hardcoding credentials when possible

---

## Troubleshooting Configuration

### "Invalid AUTH_PROVIDER_TYPE"

Check spelling and ensure it's one of: `none`, `ory`, `auth0`, `keycloak`, `cognito`

### "JWKS URL returns 404"

Verify:
1. Domain/tenant is correct
2. JWKS URL is accessible (test with curl)
3. Auth provider is responding

```bash
curl https://your-domain/.well-known/jwks.json
```

### "Storage provider fails"

Verify credentials and permissions:
- S3: Check IAM user has S3 permissions
- Azure: Check connection string is valid
- GCS: Check service account key file exists and is readable

### "CORS errors from frontend"

Update `CORS_ORIGINS` to include your frontend domain:

```bash
CORS_ORIGINS=["https://your-frontend.com"]
```

---

## Placeholder Features

### Background Tasks Requiring Implementation

This template includes background task **scaffolding** that must be implemented before production use.

| Feature | Status | Implementation Guide |
|---------|--------|---------------------|
| Email Service | ⚠️ **Placeholder** | [implementing_email_service.md](docs/implementing_email_service.md) |
| Log Archival | ⚠️ **Placeholder** | [implementing_log_archival.md](docs/implementing_log_archival.md) |
| Report Generation | ⚠️ **Placeholder** | [implementing_reports.md](docs/implementing_reports.md) |

### What "Placeholder" Means

**Current Behavior**:
- Functions log success messages (e.g., "welcome_email_sent")
- No actual operations performed (only `await asyncio.sleep(0.1)`)
- Users created/reports requested but nothing delivered

**Action Required**:
- Implement actual service integrations before production deployment
- OR remove placeholder functions if not needed for your use case

### HTTP Client Reference Examples

The file `redact_api/core/http_client.py` contains commented examples (lines 61-253):
- `verify_token_with_auth_service` - Auth service integration pattern
- `send_notification` - Notification service pattern
- `report_activity` - Analytics service pattern
- Circuit breaker and retry patterns

**These are NOT active code**. Uncomment and adapt when needed.

See [service_integration_patterns.md](docs/service_integration_patterns.md) for integration guide.

### Verification Before Deployment

```bash
# Check for unimplemented placeholders
grep -n "asyncio.sleep(0.1)" redact_api/core/background_tasks.py

# If this returns results, implement or remove those functions
```

---

## Next Steps

See [QUICKSTART.md](QUICKSTART.md) for post-generation setup.
