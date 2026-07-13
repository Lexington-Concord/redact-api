# Authentication Configuration Guide

Guide for configuring authentication providers in the FastAPI template.

## Overview

The redact_api supports multiple authentication providers. This document explains how to configure authentication for your deployment.

## Supported Authentication Providers

| Provider | Type | Best For |
|----------|------|----------|
| `none` | No authentication | Public APIs, development |
| `ory` | Open source, self-hosted | Self-hosted, privacy-focused |
| `auth0` | Commercial SaaS | Enterprise, quick setup |
| `keycloak` | Open source | Self-hosted, enterprise |
| `cognito` | AWS managed | AWS-native applications |

## Configuration

### Environment Variables

Configure authentication via environment variables in your `.env` file:

```bash
# .env

# Authentication provider selection
AUTH_PROVIDER_TYPE=ory  # Options: none, ory, auth0, keycloak, cognito

# When authentication is enabled:
AUTH_PROVIDER_URL=https://your-auth-provider.com
AUTH_PROVIDER_ISSUER=https://your-auth-provider.com/
JWT_ALGORITHM=RS256
JWT_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----

# When authentication is disabled:
# AUTH_PROVIDER_TYPE=none
# AUTH_PROVIDER_URL and other auth vars are optional
```

### Storage Configuration

Configure file storage based on your environment:

```bash
# Local storage (development)
STORAGE_PROVIDER=local
STORAGE_LOCAL_PATH=./uploads

# AWS S3 (production)
STORAGE_PROVIDER=s3
STORAGE_AWS_BUCKET=my-document-bucket
STORAGE_AWS_REGION=us-east-1

# Azure Blob Storage (production)
STORAGE_PROVIDER=azure
STORAGE_AZURE_CONTAINER=documents
STORAGE_AZURE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...

# Google Cloud Storage (production)
STORAGE_PROVIDER=gcs
STORAGE_GCS_BUCKET=my-document-bucket
STORAGE_GCS_PROJECT_ID=my-project-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
```

### Additional Configuration

```bash
# Tenant Isolation
ENFORCE_TENANT_ISOLATION=true  # or false for single-tenant mode

# CORS Configuration
CORS_ALLOWED_ORIGINS=http://localhost:3000

# Observability
ENABLE_METRICS=true
ACTIVITY_LOGGING_ENABLED=true
```

## Core Configuration

The settings are defined in `redact_api/core/config.py`:

```python
# redact_api/core/config.py

class Settings(BaseSettings):
    # ... existing fields ...

    auth_provider_type: str = Field(
        default="none",
        alias="AUTH_PROVIDER_TYPE",
        description="Authentication provider",
    )

    auth_provider_url: str | None = Field(
        default=None,
        alias="AUTH_PROVIDER_URL",
    )

    auth_provider_issuer: str | None = Field(
        default=None,
        alias="AUTH_PROVIDER_ISSUER",
    )

    jwt_algorithm: str = Field(
        default="RS256",
        alias="JWT_ALGORITHM",
    )

    jwt_public_key: str | None = Field(
        default=None,
        alias="JWT_PUBLIC_KEY",
    )
```

## Middleware Configuration

Authentication middleware is configured in `redact_api/main.py`:

```python
# redact_api/main.py

# When authentication is enabled (AUTH_PROVIDER_TYPE != 'none'):
from redact_api.core.auth import AuthMiddleware
app.add_middleware(AuthMiddleware)

# When multi-tenant isolation is enabled (ENFORCE_TENANT_ISOLATION=true):
from redact_api.core.tenants import TenantIsolationMiddleware
app.add_middleware(TenantIsolationMiddleware)
```

To enable/disable authentication:
1. Set `AUTH_PROVIDER_TYPE` in your `.env` file
2. Configure the provider-specific settings
3. Restart the application

## Test Configuration

Test mocks are available for each auth provider:

```python
# redact_api/tests/conftest.py

# Import the appropriate mock for your auth provider:
from redact_api.tests.mocks.auth_providers import (
    mock_ory_provider,      # When using Ory
    mock_auth0_provider,    # When using Auth0
    mock_keycloak_provider, # When using Keycloak
    mock_cognito_provider,  # When using Cognito
)

# Tests will use mocked auth provider based on configuration
```

## Provider-Specific Setup

### Ory Setup

1. **Required Steps**:
   - Create Ory project at https://console.ory.sh
   - Get project URL (e.g., https://my-project.ory.sh)
   - Set AUTH_PROVIDER_URL

2. **Configuration**:
   - JWT algorithm defaults to RS256
   - Issuer defaults to provider URL
   - Test fixtures provided

3. **Documentation Reference**:
   - `docs/auth_providers/ory_setup.md`

### Auth0 Setup

1. **Required Steps**:
   - Create Auth0 application at https://manage.auth0.com
   - Get domain and application ID
   - Create API

2. **Configuration**:
   - JWKS endpoint configured automatically
   - Token introspection setup
   - Public key fetched automatically

3. **Documentation Reference**:
   - `docs/auth_providers/auth0_setup.md`

### Keycloak Setup

1. **Required Steps**:
   - Self-host or use managed Keycloak
   - Create realm
   - Create client application

2. **Configuration**:
   - Token endpoint configured
   - Token validation setup
   - JWKS URL set up

3. **Documentation Reference**:
   - `docs/auth_providers/keycloak_setup.md`

### Cognito Setup

1. **Required Steps**:
   - Create AWS Cognito user pool
   - Create app client
   - Configure resource server

2. **Configuration**:
   - User pool ID extraction
   - JWKS URL setup
   - Token validation

3. **Documentation Reference**:
   - `docs/auth_providers/cognito_setup.md`

## Quick Start

### 1. Configure Your Environment

```bash
cd redact_api

# Copy the example environment file
cp .env.example .env

# Edit .env with your settings:
# - Set DATABASE_URL
# - Set AUTH_PROVIDER_TYPE and related settings
# - Configure STORAGE_PROVIDER if needed
```

### 2. Run Database Migrations

```bash
uv run alembic upgrade head
```

### 3. Start Development Server

```bash
uv run fastapi dev redact_api/main.py
```

### 4. Verify Setup

```bash
# View API docs
open http://localhost:8000/docs

# Run tests
uv run pytest tests/ -v
```

## Advanced Configuration

### Custom Provider

For custom auth providers:

```python
# redact_api/core/auth_providers/custom.py

from redact_api.core.auth import AuthProvider

class CustomAuthProvider(AuthProvider):
    """Custom authentication provider implementation."""

    async def validate_token(self, token: str) -> dict:
        """Validate token with custom logic."""
        # Custom implementation
        pass
```

### Multiple Providers

For supporting multiple providers:

```python
# redact_api/core/auth.py

PRIMARY_PROVIDER = get_provider(settings.auth_provider_type)
FALLBACK_PROVIDERS = [...]

async def validate_token(token: str) -> dict:
    """Try primary, fall back to alternatives."""
    try:
        return await PRIMARY_PROVIDER.validate_token(token)
    except Exception:
        for provider in FALLBACK_PROVIDERS:
            try:
                return await provider.validate_token(token)
            except Exception:
                continue
        raise
```

## Testing Auth Providers

```bash
# Test Ory
pytest tests/test_auth_ory.py

# Test Auth0
pytest tests/test_auth_auth0.py

# Test Keycloak
pytest tests/test_auth_keycloak.py

# Test Cognito
pytest tests/test_auth_cognito.py

# Test all
pytest tests/test_auth_*.py
```

## See Also

- [Auth Configuration](../redact_api/core/auth.py) - Authentication implementation
- [Resilience Patterns](resilience_patterns.md) - Handle auth provider outages
- [Testing External Services](testing_external_services.md) - Mock auth providers in tests
