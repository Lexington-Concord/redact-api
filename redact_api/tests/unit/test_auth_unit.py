"""Unit tests for auth module covering edge cases and helper functions.

Tests the individual functions and edge cases not covered by integration tests:
- JWKS caching
- Token verification paths
- Cognito JWKS validation
- Error handling
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import HTTPException

from redact_api.core.auth import (
    AuthMiddleware,
    AuthProviderType,
    CurrentUser,
    TokenValidationError,
    _decode_jwt_with_key,
    _extract_token_kid,
    _extract_user_from_claims,
    _fetch_jwks_for_cognito,
    _find_public_key_in_jwks,
    _verify_token_local,
    _verify_token_remote_auth0,
    _verify_token_remote_cognito,
    _verify_token_remote_keycloak,
    _verify_token_remote_ory,
    clear_jwks_cache,
    get_current_user,
    get_current_user_optional,
    get_jwks_cached,
    verify_token,
)

if TYPE_CHECKING:
    from collections.abc import Generator


# Test constants
TEST_SECRET = "test-secret-key-for-jwt-signing"
TEST_ISSUER = "https://test-auth.example.com"
VALID_USER_ID = str(uuid4())
VALID_EMAIL = "test@example.com"
VALID_ORG_ID = str(uuid4())
FUTURE_EXP = int((datetime.now(UTC) + timedelta(hours=1)).timestamp())


@pytest.fixture(autouse=True)
def clear_cache() -> Generator[None]:
    """Clear JWKS cache before and after each test."""
    clear_jwks_cache()
    yield
    clear_jwks_cache()


class TestVerifyTokenLocal:
    """Tests for _verify_token_local function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_auth_disabled(self) -> None:
        """Should return None when auth provider is NONE."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_type = AuthProviderType.NONE

            result = await _verify_token_local("some-token")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_public_key(self) -> None:
        """Should return None and log warning when JWT_PUBLIC_KEY not set."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_type = AuthProviderType.ORY
            mock_settings.jwt_public_key = None

            result = await _verify_token_local("some-token")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_expired_token(self) -> None:
        """Should return None for expired token."""
        expired_claims = {
            "sub": VALID_USER_ID,
            "email": VALID_EMAIL,
            "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
            "iat": int(datetime.now(UTC).timestamp()) - 7200,
            "iss": TEST_ISSUER,
        }
        expired_token = jwt.encode(expired_claims, TEST_SECRET, algorithm="HS256")

        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_type = AuthProviderType.AUTH0
            mock_settings.jwt_public_key = TEST_SECRET
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.auth_provider_issuer = TEST_ISSUER

            result = await _verify_token_local(expired_token)
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_invalid_token(self) -> None:
        """Should return None for malformed token."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_type = AuthProviderType.AUTH0
            mock_settings.jwt_public_key = TEST_SECRET
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.auth_provider_issuer = TEST_ISSUER

            result = await _verify_token_local("not-a-valid-jwt")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_generic_exception(self) -> None:
        """Should return None and log error on unexpected exception."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_type = AuthProviderType.AUTH0
            mock_settings.jwt_public_key = TEST_SECRET
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.auth_provider_issuer = TEST_ISSUER

            with patch("jwt.decode", side_effect=Exception("Unexpected error")):
                result = await _verify_token_local("some-token")
                assert result is None

    @pytest.mark.asyncio
    async def test_returns_claims_on_valid_token(self) -> None:
        """Should return decoded claims for valid token."""
        valid_claims = {
            "sub": VALID_USER_ID,
            "email": VALID_EMAIL,
            "exp": FUTURE_EXP,
            "iat": int(datetime.now(UTC).timestamp()),
            "iss": TEST_ISSUER,
        }
        valid_token = jwt.encode(valid_claims, TEST_SECRET, algorithm="HS256")

        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_type = AuthProviderType.AUTH0
            mock_settings.jwt_public_key = TEST_SECRET
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.auth_provider_issuer = TEST_ISSUER

            result = await _verify_token_local(valid_token)
            assert result is not None
            assert result["sub"] == VALID_USER_ID


class TestGetJwksCached:
    """Tests for get_jwks_cached function."""

    @pytest.mark.asyncio
    async def test_fetches_and_caches_jwks(self) -> None:
        """Should fetch JWKS and cache it."""
        mock_jwks = {"keys": [{"kid": "key1", "kty": "RSA"}]}
        jwks_url = "https://auth.example.com/.well-known/jwks.json"

        with patch("redact_api.core.auth.http_client") as mock_http:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_jwks
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_http.return_value = mock_client

            result = await get_jwks_cached(jwks_url)
            assert result == mock_jwks

    @pytest.mark.asyncio
    async def test_returns_cached_jwks(self) -> None:
        """Should return cached JWKS without fetching again."""
        mock_jwks = {"keys": [{"kid": "cached-key", "kty": "RSA"}]}
        jwks_url = "https://auth.example.com/.well-known/jwks.json"

        with patch("redact_api.core.auth.http_client") as mock_http:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_jwks
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_http.return_value = mock_client

            # First call - fetches
            result1 = await get_jwks_cached(jwks_url)
            assert result1 == mock_jwks

            # Second call - should use cache
            result2 = await get_jwks_cached(jwks_url)
            assert result2 == mock_jwks

            # Should only have been called once
            assert mock_client.get.call_count == 1


class TestClearJwksCache:
    """Tests for clear_jwks_cache function."""

    @pytest.mark.asyncio
    async def test_clears_cache(self) -> None:
        """Should clear all cached JWKS data."""
        mock_jwks = {"keys": [{"kid": "key1", "kty": "RSA"}]}
        jwks_url = "https://auth.example.com/.well-known/jwks.json"

        with patch("redact_api.core.auth.http_client") as mock_http:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_jwks
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_http.return_value = mock_client

            # Populate cache
            await get_jwks_cached(jwks_url)
            assert mock_client.get.call_count == 1

            # Clear cache
            clear_jwks_cache()

            # Next call should fetch again
            await get_jwks_cached(jwks_url)
            assert mock_client.get.call_count == 2


class TestVerifyTokenRemoteOry:
    """Tests for _verify_token_remote_ory function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_url_not_configured(self) -> None:
        """Should return None when auth_provider_url is not set."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = None

            result = await _verify_token_remote_ory("some-token")
            assert result is None


class TestVerifyTokenRemoteAuth0:
    """Tests for _verify_token_remote_auth0 function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_url_not_configured(self) -> None:
        """Should return None when auth_provider_url is not set."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = None

            result = await _verify_token_remote_auth0("some-token")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self) -> None:
        """Should return None on network error."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = "https://test.auth0.com"

            with patch("redact_api.core.auth.http_client") as mock_http:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(side_effect=httpx.RequestError("Network error"))
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_http.return_value = mock_client

                result = await _verify_token_remote_auth0("some-token")
                assert result is None

    @pytest.mark.asyncio
    async def test_returns_claims_on_success(self) -> None:
        """Should return claims on successful userinfo call."""
        userinfo = {"sub": VALID_USER_ID, "email": VALID_EMAIL}

        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = "https://test.auth0.com"

            with patch("redact_api.core.auth.http_client") as mock_http:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = userinfo
                mock_client.get = AsyncMock(return_value=mock_response)
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_http.return_value = mock_client

                result = await _verify_token_remote_auth0("valid-token")
                assert result == userinfo


class TestVerifyTokenRemoteKeycloak:
    """Tests for _verify_token_remote_keycloak function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_url_not_configured(self) -> None:
        """Should return None when auth_provider_url is not set."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = None

            result = await _verify_token_remote_keycloak("some-token")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_inactive_token(self) -> None:
        """Should return None when token is not active."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = "https://keycloak.example.com/realms/test"

            with patch("redact_api.core.auth.http_client") as mock_http:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"active": False}
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_http.return_value = mock_client

                result = await _verify_token_remote_keycloak("inactive-token")
                assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_failed_status(self) -> None:
        """Should return None on non-200 status."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = "https://keycloak.example.com/realms/test"

            with patch("redact_api.core.auth.http_client") as mock_http:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 500
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_http.return_value = mock_client

                result = await _verify_token_remote_keycloak("some-token")
                assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self) -> None:
        """Should return None on network error."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = "https://keycloak.example.com/realms/test"

            with patch("redact_api.core.auth.http_client") as mock_http:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(side_effect=httpx.RequestError("Network error"))
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_http.return_value = mock_client

                result = await _verify_token_remote_keycloak("some-token")
                assert result is None

    @pytest.mark.asyncio
    async def test_returns_claims_on_success(self) -> None:
        """Should return claims on successful introspection."""
        claims = {"active": True, "sub": VALID_USER_ID, "email": VALID_EMAIL}

        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = "https://keycloak.example.com/realms/test"

            with patch("redact_api.core.auth.http_client") as mock_http:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = claims
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_http.return_value = mock_client

                result = await _verify_token_remote_keycloak("valid-token")
                assert result == claims


class TestFetchJwksForCognito:
    """Tests for _fetch_jwks_for_cognito function."""

    @pytest.mark.asyncio
    async def test_returns_success_with_jwks(self) -> None:
        """Should return success result with JWKS."""
        mock_jwks = {"keys": [{"kid": "key1", "kty": "RSA"}]}
        jwks_url = "https://cognito.example.com/.well-known/jwks.json"

        with patch("redact_api.core.auth.get_jwks_cached", return_value=mock_jwks):
            result = await _fetch_jwks_for_cognito(jwks_url)
            assert result.success is True
            assert result.jwks == mock_jwks

    @pytest.mark.asyncio
    async def test_returns_failure_on_request_error(self) -> None:
        """Should return failure on request error."""
        jwks_url = "https://cognito.example.com/.well-known/jwks.json"

        with patch(
            "redact_api.core.auth.get_jwks_cached",
            side_effect=httpx.RequestError("Connection failed"),
        ):
            result = await _fetch_jwks_for_cognito(jwks_url)
            assert result.success is False
            assert result.error_type == "request_error"

    @pytest.mark.asyncio
    async def test_returns_failure_on_http_status_error(self) -> None:
        """Should return failure on HTTP status error."""
        jwks_url = "https://cognito.example.com/.well-known/jwks.json"

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch(
            "redact_api.core.auth.get_jwks_cached",
            side_effect=httpx.HTTPStatusError("Not found", request=MagicMock(), response=mock_response),
        ):
            result = await _fetch_jwks_for_cognito(jwks_url)
            assert result.success is False
            assert result.error_type == "http_status_error"


class TestExtractTokenKid:
    """Tests for _extract_token_kid function."""

    def test_returns_kid_on_valid_token(self) -> None:
        """Should return kid from valid token header."""
        # Create token with kid in header
        claims = {"sub": VALID_USER_ID, "exp": FUTURE_EXP}
        token = jwt.encode(claims, TEST_SECRET, algorithm="HS256", headers={"kid": "my-key-id"})

        result = _extract_token_kid(token)
        assert result.success is True
        assert result.kid == "my-key-id"

    def test_returns_failure_on_missing_kid(self) -> None:
        """Should return failure when kid is missing from header."""
        # Create token without kid
        claims = {"sub": VALID_USER_ID, "exp": FUTURE_EXP}
        token = jwt.encode(claims, TEST_SECRET, algorithm="HS256")

        result = _extract_token_kid(token)
        assert result.success is False
        assert result.error_type == "missing_kid"

    def test_returns_failure_on_decode_error(self) -> None:
        """Should return failure on malformed token."""
        result = _extract_token_kid("not-a-valid-jwt")
        assert result.success is False
        assert result.error_type == "decode_error"


class TestFindPublicKeyInJwks:
    """Tests for _find_public_key_in_jwks function."""

    def test_returns_none_when_kid_not_found(self) -> None:
        """Should return None when kid is not in JWKS."""
        jwks: dict[str, Any] = {"keys": [{"kid": "other-key", "kty": "RSA"}]}

        result = _find_public_key_in_jwks(jwks, "missing-key")
        assert result is None

    def test_returns_none_on_empty_keys(self) -> None:
        """Should return None when keys array is empty."""
        jwks: dict[str, Any] = {"keys": []}

        result = _find_public_key_in_jwks(jwks, "any-key")
        assert result is None

    def test_returns_none_on_invalid_key_format(self) -> None:
        """Should return None when key cannot be parsed."""
        # Mock from_jwk to raise ValueError (which is caught by the code)
        jwks: dict[str, Any] = {"keys": [{"kid": "bad-key", "kty": "RSA"}]}

        with patch("jwt.algorithms.RSAAlgorithm.from_jwk", side_effect=ValueError("Invalid key")):
            result = _find_public_key_in_jwks(jwks, "bad-key")
            assert result is None


class TestDecodeJwtWithKey:
    """Tests for _decode_jwt_with_key function."""

    def test_returns_none_on_expired_token(self) -> None:
        """Should return None for expired token."""
        expired_claims = {
            "sub": VALID_USER_ID,
            "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
            "iss": TEST_ISSUER,
        }
        expired_token = jwt.encode(expired_claims, TEST_SECRET, algorithm="HS256")

        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_issuer = TEST_ISSUER

            # Use a mock key that would decode HS256
            result = _decode_jwt_with_key(expired_token, TEST_SECRET)  # type: ignore[arg-type]
            assert result is None

    def test_returns_none_on_invalid_token(self) -> None:
        """Should return None for invalid token."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_issuer = TEST_ISSUER

            result = _decode_jwt_with_key("invalid-token", TEST_SECRET)  # type: ignore[arg-type]
            assert result is None


class TestVerifyTokenRemoteCognito:
    """Tests for _verify_token_remote_cognito function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_url_not_configured(self) -> None:
        """Should return None when auth_provider_url is not set."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = None

            result = await _verify_token_remote_cognito("some-token")
            assert result is None

    @pytest.mark.asyncio
    async def test_uses_local_validation_with_public_key(self) -> None:
        """Should use local validation when jwt_public_key is set."""
        valid_claims = {
            "sub": VALID_USER_ID,
            "email": VALID_EMAIL,
            "exp": FUTURE_EXP,
            "iat": int(datetime.now(UTC).timestamp()),
            "iss": TEST_ISSUER,
        }
        valid_token = jwt.encode(valid_claims, TEST_SECRET, algorithm="HS256")

        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = "https://cognito.example.com"
            mock_settings.jwt_public_key = TEST_SECRET
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.auth_provider_issuer = TEST_ISSUER
            mock_settings.auth_provider_type = AuthProviderType.COGNITO

            result = await _verify_token_remote_cognito(valid_token)
            assert result is not None
            assert result["sub"] == VALID_USER_ID

    @pytest.mark.asyncio
    async def test_returns_none_on_jwks_fetch_failure(self) -> None:
        """Should return None when JWKS fetch fails."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = "https://cognito.example.com"
            mock_settings.jwt_public_key = None

            with patch(
                "redact_api.core.auth._fetch_jwks_for_cognito",
                return_value=MagicMock(success=False, jwks=None),
            ):
                result = await _verify_token_remote_cognito("some-token")
                assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_kid_extraction_failure(self) -> None:
        """Should return None when kid extraction fails."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_url = "https://cognito.example.com"
            mock_settings.jwt_public_key = None

            with (
                patch(
                    "redact_api.core.auth._fetch_jwks_for_cognito",
                    return_value=MagicMock(success=True, jwks={"keys": []}),
                ),
                patch(
                    "redact_api.core.auth._extract_token_kid",
                    return_value=MagicMock(success=False, kid=None),
                ),
            ):
                result = await _verify_token_remote_cognito("some-token")
                assert result is None


class TestVerifyToken:
    """Tests for verify_token function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_auth_disabled(self) -> None:
        """Should return None when auth is disabled."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_type = AuthProviderType.NONE

            result = await verify_token("any-token")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_validator_found(self) -> None:
        """Should return None when provider validator is not found."""
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_type = AuthProviderType.ORY
            mock_settings.jwt_public_key = None

            # Mock to return None from validator lookup
            with patch.dict(
                "redact_api.core.auth.verify_token.__globals__",
                {"provider_validators": {}},
            ):
                # This simulates the case where no validator is found
                # Use direct patch on the function level
                pass

        # Test that local validation failure + no remote validator = None
        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_type = AuthProviderType.ORY
            mock_settings.jwt_public_key = None
            mock_settings.auth_provider_url = None  # Will cause Ory to return None

            result = await verify_token("some-token")
            assert result is None


class TestExtractUserFromClaims:
    """Tests for _extract_user_from_claims function."""

    def test_uses_preferred_username_as_email(self) -> None:
        """Should use preferred_username when email is missing."""
        claims: dict[str, Any] = {
            "sub": VALID_USER_ID,
            "preferred_username": "user@example.com",
        }
        user = _extract_user_from_claims(claims)
        assert user.email == "user@example.com"

    def test_handles_invalid_org_id_format(self) -> None:
        """Should handle and log invalid organization_id format."""
        claims: dict[str, Any] = {
            "sub": VALID_USER_ID,
            "email": VALID_EMAIL,
            "org_id": "not-a-valid-uuid",
        }
        user = _extract_user_from_claims(claims)
        assert user.organization_id is None

    def test_extracts_organization_id_claim(self) -> None:
        """Should extract organization_id from claims."""
        claims: dict[str, Any] = {
            "sub": VALID_USER_ID,
            "email": VALID_EMAIL,
            "organization_id": VALID_ORG_ID,
        }
        user = _extract_user_from_claims(claims)
        assert str(user.organization_id) == VALID_ORG_ID

    def test_handles_malformed_email_format(self) -> None:
        """Document current behavior: accepts any string as email.

        The current implementation is permissive and accepts any string as email.
        This test documents that behavior - if stricter validation is needed,
        this test should be updated to expect TokenValidationError.
        """
        claims: dict[str, Any] = {
            "sub": VALID_USER_ID,
            "email": "not-a-valid-email",
        }
        user = _extract_user_from_claims(claims)
        # Current behavior: accepts invalid email format
        assert user.email == "not-a-valid-email"

    def test_rejects_empty_email_string(self) -> None:
        """Should reject empty string email as missing email."""
        claims: dict[str, Any] = {
            "sub": VALID_USER_ID,
            "email": "",
        }
        with pytest.raises(TokenValidationError, match="Missing email claim"):
            _extract_user_from_claims(claims)

    def test_prefers_email_over_preferred_username(self) -> None:
        """Should use email claim when both email and preferred_username exist."""
        claims: dict[str, Any] = {
            "sub": VALID_USER_ID,
            "email": "primary@example.com",
            "preferred_username": "fallback@example.com",
        }
        user = _extract_user_from_claims(claims)
        assert user.email == "primary@example.com"


class TestAuthMiddleware:
    """Tests for AuthMiddleware class."""

    @pytest.mark.asyncio
    async def test_skips_auth_when_disabled(self) -> None:
        """Should skip auth when provider is NONE."""
        middleware = AuthMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.headers.get.return_value = None
        mock_request.url.path = "/api/resource"
        mock_request.state = MagicMock()

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)

        with patch("redact_api.core.auth.settings") as mock_settings:
            mock_settings.auth_provider_type = AuthProviderType.NONE

            response = await middleware.dispatch(mock_request, mock_call_next)
            assert response == mock_response
            assert mock_request.state.user is None

    @pytest.mark.asyncio
    async def test_skips_public_paths(self) -> None:
        """Should skip auth for public paths."""
        middleware = AuthMiddleware(app=MagicMock())

        public_paths = ["/health", "/ping", "/docs", "/openapi.json", "/metrics"]

        for path in public_paths:
            mock_request = MagicMock()
            mock_request.headers.get.return_value = None
            mock_request.url.path = path
            mock_request.state = MagicMock()

            mock_response = MagicMock()
            mock_call_next = AsyncMock(return_value=mock_response)

            with patch("redact_api.core.auth.settings") as mock_settings:
                mock_settings.auth_provider_type = AuthProviderType.ORY

                response = await middleware.dispatch(mock_request, mock_call_next)
                assert response == mock_response
                assert mock_request.state.user is None


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    def test_returns_user_from_request_state(self) -> None:
        """Should return user from request.state."""
        mock_user = CurrentUser(id=uuid4(), email=VALID_EMAIL)
        mock_request = MagicMock()
        mock_request.state.user = mock_user

        result = get_current_user(mock_request)
        assert result == mock_user

    def test_raises_401_when_no_user(self) -> None:
        """Should raise 401 when user is not in request state."""
        mock_request = MagicMock()
        mock_request.state.user = None

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(mock_request)

        assert exc_info.value.status_code == 401


class TestGetCurrentUserOptional:
    """Tests for get_current_user_optional dependency."""

    def test_returns_user_when_authenticated(self) -> None:
        """Should return user when authenticated."""
        mock_user = CurrentUser(id=uuid4(), email=VALID_EMAIL)
        mock_request = MagicMock()
        mock_request.state.user = mock_user

        result = get_current_user_optional(mock_request)
        assert result == mock_user

    def test_returns_none_when_not_authenticated(self) -> None:
        """Should return None when not authenticated."""
        mock_request = MagicMock()
        mock_request.state.user = None

        result = get_current_user_optional(mock_request)
        assert result is None
