# Testing External Services

Guide for testing code that integrates with external services (auth providers, cloud storage, payment processors, etc.) without requiring live credentials or active infrastructure.

## Table of Contents

1. [Philosophy](#philosophy)
2. [Mock Fixtures](#mock-fixtures)
3. [Integration Patterns](#integration-patterns)
4. [Error Scenarios](#error-scenarios)
5. [Best Practices](#best-practices)
6. [Examples](#examples)

## Philosophy

### Goals

- **Isolation**: Tests don't require live external services
- **Reproducibility**: Tests produce consistent results regardless of external state
- **Speed**: No network latency; tests run in milliseconds
- **Safety**: Can run in CI/CD without credentials
- **Completeness**: Test both success and failure paths

### When to Mock vs. Integration Test

**Always use mocks:**
- Authentication provider calls
- Storage provider operations (upload/download)
- Payment processing
- SMS/email sending

**Can use real services (with caution):**
- Development environment only
- Behind feature flags
- On explicit CI/CD pipeline (separate from unit tests)

## Mock Fixtures

### Auth Provider Mocks

Each auth provider mock patches the external service and tracks calls:

#### Ory
```python
def test_ory_authentication(mock_ory_provider, client):
    """Test with mocked Ory provider."""
    token = mock_ory_provider["test_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/users", headers=headers)
    assert response.status_code == 200
```

#### Auth0
```python
def test_auth0_token_validation(mock_auth0_provider, client):
    """Test Auth0 token validation without Auth0 API."""
    token = mock_auth0_provider["test_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/profile", headers=headers)
    assert response.status_code == 200
```

#### Keycloak
```python
def test_keycloak_login(mock_keycloak_provider, client):
    """Test Keycloak integration without Keycloak server."""
    realm = mock_keycloak_provider["test_realm"]
    token = mock_keycloak_provider["test_token"]

    response = await client.post(
        f"/auth/realms/{realm}/protocol/openid-connect/token",
        json={"username": "test", "password": "test"}
    )
    # Would typically return token in response
```

#### Cognito
```python
def test_cognito_user_pool(mock_cognito_provider, client):
    """Test AWS Cognito without AWS credentials."""
    user_pool_id = mock_cognito_provider["test_user_pool_id"]
    token = mock_cognito_provider["test_token"]

    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get("/user-profile", headers=headers)
    assert response.status_code == 200
```

### Storage Provider Mocks

Storage mocks track uploads/downloads and allow simulating errors:

#### S3 Storage
```python
def test_document_upload_s3(mock_s3_storage, client):
    """Test document upload to S3."""
    response = await client.post(
        "/documents/upload",
        files={"file": ("test.pdf", b"PDF content", "application/pdf")}
    )
    assert response.status_code == 201

    # Verify mock tracked the upload
    assert len(mock_s3_storage['uploaded_files']) == 1
    assert mock_s3_storage['uploaded_files'][0]['content_type'] == 'application/pdf'

def test_document_upload_s3_failure(mock_s3_storage, client):
    """Test S3 upload failure handling."""
    # Configure mock to simulate error
    mock_s3_storage['should_fail'] = True
    mock_s3_storage['failure_reason'] = 'Access Denied'

    response = await client.post(
        "/documents/upload",
        files={"file": ("test.pdf", b"PDF content", "application/pdf")}
    )
    # Endpoint should handle S3 errors gracefully
    assert response.status_code == 503
```

#### Azure Storage
```python
def test_blob_upload_azure(mock_azure_storage, client):
    """Test file upload to Azure Blob Storage."""
    response = await client.post(
        "/files/upload",
        files={"file": ("test.txt", b"content")}
    )
    assert response.status_code == 201
    assert len(mock_azure_storage['uploaded_files']) == 1

def test_blob_download_azure(mock_azure_storage, client):
    """Test file download from Azure."""
    # First upload
    await client.post("/files/upload", files={"file": ("test.txt", b"content")})

    # Then download
    doc_id = "test-doc-id"
    response = await client.get(f"/files/{doc_id}/download")
    assert response.status_code == 200
    assert len(mock_azure_storage['downloaded_files']) == 1
```

#### GCS Storage
```python
def test_gcs_upload(mock_gcs_storage, client):
    """Test upload to Google Cloud Storage."""
    response = await client.post(
        "/documents",
        files={"file": ("doc.pdf", b"content", "application/pdf")}
    )
    assert response.status_code == 201
    assert mock_gcs_storage['bucket_name'] == 'test-bucket'
```

## Integration Patterns

### Composition: Multiple Mocks

```python
def test_user_creation_with_auth_and_storage(
    mock_auth0_provider,
    mock_s3_storage,
    client
):
    """Test endpoint using multiple mocked services."""
    # Use auth mock
    token = mock_auth0_provider["test_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create user (which uploads avatar to S3)
    response = await client.post(
        "/users",
        headers=headers,
        files={"avatar": ("avatar.jpg", b"JPEG data")},
        json={"name": "Test User", "email": "test@example.com"}
    )

    assert response.status_code == 201
    # Verify both services were used
    assert len(mock_s3_storage['uploaded_files']) == 1
```

### Dependency Injection

```python
# In tests/mocks/__init__.py
@pytest.fixture
def mock_services(mock_ory_provider, mock_s3_storage):
    """Composite fixture providing all mocked services."""
    return {
        "auth": mock_ory_provider,
        "storage": mock_s3_storage,
    }

# In test file
def test_with_composite_mock(mock_services, client):
    """Use composite mock for cleaner tests."""
    token = mock_services["auth"]["test_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post(
        "/documents",
        headers=headers,
        files={"file": ("doc.pdf", b"content")}
    )
    assert response.status_code == 201
    assert len(mock_services["storage"]['uploaded_files']) == 1
```

## Error Scenarios

### Simulating Service Failures

```python
def test_storage_unavailable(mock_s3_storage, client):
    """Test graceful handling of storage service outage."""
    # Configure mock to fail
    mock_s3_storage['should_fail'] = True
    mock_s3_storage['failure_reason'] = 'Service Unavailable'

    response = await client.post(
        "/documents/upload",
        files={"file": ("test.pdf", b"content")}
    )

    # Verify endpoint returns appropriate error
    assert response.status_code == 503
    assert 'storage' in response.json()['detail'].lower()

def test_auth_token_invalid(mock_ory_provider, client):
    """Test with invalid authentication token."""
    headers = {"Authorization": "Bearer invalid_token"}

    response = await client.get("/users", headers=headers)
    assert response.status_code == 401
    assert 'unauthorized' in response.json()['detail'].lower()

def test_auth_token_expired(mock_ory_provider, client):
    """Test with expired token."""
    # Mock would return expired token
    expired_token = "expired_" + mock_ory_provider["test_token"]
    headers = {"Authorization": f"Bearer {expired_token}"}

    response = await client.get("/users", headers=headers)
    assert response.status_code == 401
```

### Permission Denied

```python
def test_cross_tenant_storage_access(mock_s3_storage, client):
    """Test that users cannot access other organizations' files."""
    # User A's token
    headers_a = {"Authorization": f"Bearer token_user_a"}

    # Try to download User B's file
    response = await client.get(
        "/documents/user-b-doc-id/download",
        headers=headers_a
    )

    # Should be denied
    assert response.status_code == 403
```

## Best Practices

### 1. Always Mock in Tests

```python
# GOOD: Test is isolated and fast
def test_upload(mock_s3_storage, client):
    response = await client.post("/documents", files={...})
    assert response.status_code == 201

# BAD: Test requires live S3 access
def test_upload_real_s3(client):
    response = await client.post("/documents", files={...})  # Will fail without real S3
```

### 2. Test Error Paths

```python
def test_upload_and_error_scenarios(mock_s3_storage, client):
    """Test both success and failure paths."""
    # Success path
    response = await client.post("/documents", files={...})
    assert response.status_code == 201

    # Failure path
    mock_s3_storage['should_fail'] = True
    response = await client.post("/documents", files={...})
    assert response.status_code == 503
```

### 3. Verify Mock Interactions

```python
def test_document_delete_calls_storage(mock_s3_storage, client):
    """Verify that delete endpoint calls storage service."""
    # Upload a document first
    await client.post("/documents", files={"file": ("test.pdf", b"content")})
    doc_id = mock_s3_storage['uploaded_files'][0]['document_id']

    # Delete it
    response = await client.delete(f"/documents/{doc_id}")
    assert response.status_code == 204

    # Verify storage service was called
    assert doc_id in mock_s3_storage['deleted_files']
```

### 4. Use Fixtures for Reusability

```python
# Create a composite fixture for tests needing multiple mocks
@pytest.fixture
def authenticated_s3_client(mock_ory_provider, mock_s3_storage, client):
    """Provide client with both auth and storage mocked."""
    def _client_with_auth(method, path, **kwargs):
        token = mock_ory_provider["test_token"]
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        kwargs["headers"] = headers
        return getattr(client, method)(path, **kwargs)

    return _client_with_auth

# Use in tests
def test_authenticated_upload(authenticated_s3_client):
    response = authenticated_s3_client("post", "/documents", files={...})
    assert response.status_code == 201
```

### 5. Document Mock Limitations

```python
def test_document_with_mock_limitation():
    """
    NOTE: This mock doesn't test:
    - Actual S3 rate limiting
    - Network timeouts
    - Multipart uploads for large files
    - Bucket region failover

    For those scenarios, use integration tests with real S3.
    """
    pass
```

## Examples

### Complete Test File

```python
# tests/test_documents_with_mocks.py

import pytest
from httpx import AsyncClient

def test_upload_document(mock_s3_storage, client):
    """Test successful document upload."""
    response = await client.post(
        "/documents/upload",
        files={"file": ("document.pdf", b"%PDF-1.4...", "application/pdf")}
    )

    assert response.status_code == 201
    assert len(mock_s3_storage['uploaded_files']) == 1
    data = response.json()
    assert data['name'] == 'document.pdf'

def test_download_document(mock_s3_storage, client):
    """Test document download."""
    # Upload first
    upload_response = await client.post(
        "/documents/upload",
        files={"file": ("test.pdf", b"content")}
    )
    doc_id = upload_response.json()['id']

    # Download
    response = await client.get(f"/documents/{doc_id}/download")
    assert response.status_code == 200
    assert len(mock_s3_storage['downloaded_files']) == 1

def test_storage_failure_handling(mock_s3_storage, client):
    """Test graceful handling of storage errors."""
    mock_s3_storage['should_fail'] = True

    response = await client.post(
        "/documents/upload",
        files={"file": ("test.pdf", b"content")}
    )

    assert response.status_code == 503
    assert 'service' in response.json()['detail'].lower()

def test_delete_nonexistent_document(client):
    """Test deleting document that doesn't exist."""
    response = await client.delete("/documents/nonexistent-id")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_concurrent_uploads(mock_s3_storage, client):
    """Test multiple concurrent uploads."""
    import asyncio

    async def upload():
        return await client.post(
            "/documents/upload",
            files={"file": ("test.pdf", b"content")}
        )

    results = await asyncio.gather(upload(), upload(), upload())

    assert all(r.status_code == 201 for r in results)
    assert len(mock_s3_storage['uploaded_files']) == 3
```

## See Also

- [Activity Logging](ACTIVITY_LOGGING.md) - Testing activity logs from external operations
- [Test Helpers](../tests/helpers/validation.py) - Reusable assertions for API responses
- [Settings Fixtures](../tests/fixtures/settings.py) - Testing with different configurations
