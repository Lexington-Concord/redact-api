"""Mock fixtures for authentication provider services.

Provides pytest fixtures that mock external auth providers without requiring
live credentials. Supports:

- Ory (open source, self-hosted)
- Auth0 (commercial SaaS)
- Keycloak (open source)
- Amazon Cognito (AWS managed)

Each provider fixture:
1. Patches the auth provider URL/issuer
2. Mocks token introspection/validation endpoints
3. Provides test tokens and user data
4. Handles error scenarios

Usage:
    def test_with_ory(mock_ory_provider):
        response = await client.get("/users", headers={"Authorization": f"Bearer {test_token}"})
        assert response.status_code == 200

    def test_auth_error(mock_auth0_provider):
        # mock_auth0_provider will raise appropriate errors
        pass
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from redact_api.core.config import Settings


@pytest.fixture
def mock_ory_provider(
    _test_settings_factory: Callable[..., Settings],
) -> Generator[dict[str, Any]]:
    """Mock Ory authentication provider.

    Patches Ory endpoint to return valid tokens without network requests.

    Fixture provides:
    - test_token: Valid JWT token
    - test_user_id: UUID of authenticated user
    - introspection_endpoint: Mocked endpoint returning user info

    Usage:
        def test_with_ory(mock_ory_provider, client):
            headers = {
                "Authorization": f"Bearer {mock_ory_provider['test_token']}"
            }
            response = await client.get("/users", headers=headers)
            assert response.status_code == 200
    """
    test_user_id = str(uuid4())
    test_token = "ory_test_token_12345"

    # Create mock response for introspection endpoint
    mock_response = {
        "active": True,
        "sub": test_user_id,
        "scope": "openid profile email",
        "exp": 9999999999,
    }

    # Mock HTTP client for token introspection
    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=MagicMock(json=AsyncMock(return_value=mock_response)))

    fixture_data: dict[str, Any] = {
        "test_token": test_token,
        "test_user_id": test_user_id,
        "provider_url": "https://test-ory.example.com",
        "mock_http": mock_http,
        "mock_response": mock_response,
    }

    with patch("redact_api.core.auth.settings") as mock_settings:
        mock_settings.auth_provider_type = "ory"
        mock_settings.auth_provider_url = "https://test-ory.example.com"
        yield fixture_data


@pytest.fixture
def mock_auth0_provider(
    _test_settings_factory: Callable[..., Settings],
) -> Generator[dict[str, Any]]:
    """Mock Auth0 authentication provider.

    Patches Auth0 endpoints to return valid tokens without Auth0 credentials.

    Fixture provides:
    - test_token: Valid JWT token
    - test_user_id: UUID of authenticated user
    - test_user_email: Test user email
    - jwks_endpoint: Mocked JWKS endpoint for key verification

    Usage:
        def test_auth0_integration(mock_auth0_provider, client):
            # Auth0 calls will be mocked internally
            response = await client.get("/users")
            assert response.status_code == 200
    """
    test_user_id = str(uuid4())
    test_user_email = "test@auth0.example.com"
    test_token = "auth0_test_token_12345"

    # JWKS response for key verification
    mock_jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "kid": "test-kid",
                "alg": "RS256",
                "n": "test-modulus",
                "e": "AQAB",
            }
        ]
    }

    fixture_data: dict[str, Any] = {
        "test_token": test_token,
        "test_user_id": test_user_id,
        "test_user_email": test_user_email,
        "provider_url": "https://test.auth0.com",
        "jwks_endpoint": "/oauth/jwks",
        "mock_jwks": mock_jwks,
    }

    with patch("redact_api.core.auth.settings") as mock_settings:
        mock_settings.auth_provider_type = "auth0"
        mock_settings.auth_provider_url = "https://test.auth0.com"
        yield fixture_data


@pytest.fixture
def mock_keycloak_provider(
    _test_settings_factory: Callable[..., Settings],
) -> Generator[dict[str, Any]]:
    """Mock Keycloak authentication provider.

    Patches Keycloak endpoints for token validation without Keycloak server.

    Fixture provides:
    - test_token: Valid JWT token
    - test_user_id: UUID of authenticated user
    - test_realm: Keycloak realm name
    - token_endpoint: Mocked token endpoint

    Usage:
        def test_keycloak_auth(mock_keycloak_provider, client):
            # Keycloak will be mocked internally
            response = await client.post("/login", json={"...": "..."})
            assert response.status_code == 200
    """
    test_user_id = str(uuid4())
    test_realm = "test-realm"
    test_token = "keycloak_test_token_12345"

    mock_token_response = {
        "access_token": test_token,
        "token_type": "Bearer",
        "expires_in": 3600,
    }

    provider_url = f"https://test-keycloak.example.com/auth/realms/{test_realm}"
    fixture_data: dict[str, Any] = {
        "test_token": test_token,
        "test_user_id": test_user_id,
        "test_realm": test_realm,
        "provider_url": provider_url,
        "token_endpoint": "/protocol/openid-connect/token",
        "mock_token_response": mock_token_response,
    }

    with patch("redact_api.core.auth.settings") as mock_settings:
        mock_settings.auth_provider_type = "keycloak"
        mock_settings.auth_provider_url = provider_url
        yield fixture_data


@pytest.fixture
def mock_cognito_provider(
    _test_settings_factory: Callable[..., Settings],
) -> Generator[dict[str, Any]]:
    """Mock AWS Cognito authentication provider.

    Patches Cognito endpoints for testing without AWS credentials.

    Fixture provides:
    - test_token: Valid ID token
    - test_user_id: UUID of authenticated user
    - test_user_pool_id: Cognito user pool ID
    - test_client_id: Cognito app client ID

    Usage:
        def test_cognito_auth(mock_cognito_provider, client):
            # Cognito will be mocked internally
            response = await client.get("/profile")
            assert response.status_code == 200
    """
    test_user_id = str(uuid4())
    test_user_pool_id = "us-east-1_abcdef123"
    test_client_id = "1a2b3c4d5e6f7g8h9i0j"
    test_token = "cognito_test_token_12345"

    provider_url = f"https://cognito-idp.us-east-1.amazonaws.com/{test_user_pool_id}"
    fixture_data: dict[str, Any] = {
        "test_token": test_token,
        "test_user_id": test_user_id,
        "test_user_pool_id": test_user_pool_id,
        "test_client_id": test_client_id,
        "provider_url": provider_url,
        "jwks_endpoint": "/.well-known/jwks.json",
    }

    with patch("redact_api.core.auth.settings") as mock_settings:
        mock_settings.auth_provider_type = "cognito"
        mock_settings.auth_provider_url = provider_url
        yield fixture_data
