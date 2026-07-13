"""JWT authentication middleware and dependency injection for FastAPI.

This module provides JWT token validation, authentication middleware, and
dependency injection for securing API endpoints. It supports multiple auth
providers (Ory, Auth0, Keycloak, AWS Cognito, etc.) through configuration.

Usage:

    # In main.py - Add middleware
    from redact_api.core.auth import AuthMiddleware
    app.add_middleware(AuthMiddleware)

    # In endpoints - Require authentication
    from redact_api.core.auth import CurrentUserDep

    @router.get("/protected")
    async def protected_endpoint(current_user: CurrentUserDep) -> dict:
        return {"user_id": current_user.id, "email": current_user.email}

    # In endpoints - Optional authentication
    from redact_api.core.auth import get_current_user_optional

    @router.get("/public")
    async def public_endpoint(
        current_user: Annotated[CurrentUser | None, Depends(get_current_user_optional)]
    ) -> dict:
        if current_user:
            return {"message": f"Hello {current_user.email}"}
        return {"message": "Hello anonymous user"}
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

import httpx
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from redact_api.core.config import settings
from redact_api.core.http_client import http_client
from redact_api.core.logging import get_logging_context
from redact_api.db.session import get_session
from redact_api.services.membership_service import is_user_member

LOGGER = logging.getLogger(__name__)

# Constants
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "
TOKEN_EXPIRY_LEEWAY_SECONDS = 10
SUCCESSFUL_HTTP_STATUS = 200
JWKS_CACHE_TTL_SECONDS = 3600  # 1 hour cache for JWKS

# JWKS cache for providers that use JSON Web Key Sets (Cognito, Auth0, etc.)
# This avoids fetching JWKS on every request, significantly improving performance.
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_url: str | None = None
_jwks_cache_expires: datetime | None = None


class AuthProviderType(StrEnum):
    """Supported authentication provider types."""

    NONE = "none"
    ORY = "ory"
    AUTH0 = "auth0"
    KEYCLOAK = "keycloak"
    COGNITO = "cognito"


class CurrentUser(BaseModel):
    """Authenticated user context extracted from JWT token.

    This model represents the authenticated user for the current request.
    It's populated by the auth middleware and available via dependency injection.

    Attributes:
        id: Unique user identifier (from 'sub' claim)
        email: User email address (from 'email' claim)
        organization_id: Tenant/organization ID (from 'org_id' claim)
    """

    id: UUID = Field(..., description="User ID from token 'sub' claim")
    email: str = Field(..., description="User email from token claims")
    organization_id: UUID | None = Field(default=None, description="Organization/tenant ID from token claims")


class TokenValidationError(Exception):
    """Raised when token validation fails."""


class JWKSFetchResult(BaseModel):
    """Result of fetching JWKS from an auth provider."""

    success: bool
    jwks: dict[str, Any] | None = None
    error_type: str | None = None


class TokenHeaderResult(BaseModel):
    """Result of extracting token header."""

    success: bool
    kid: str | None = None
    error_type: str | None = None


def _extract_bearer_token(authorization_header: str | None) -> str | None:
    """Extract Bearer token from Authorization header.

    Args:
        authorization_header: Value of Authorization header

    Returns:
        Token string if valid Bearer format, None otherwise
    """
    if not authorization_header:
        return None

    if not authorization_header.startswith(BEARER_PREFIX):
        return None

    return authorization_header[len(BEARER_PREFIX) :].strip()


async def _verify_token_local(token: str) -> dict[str, Any] | None:
    """Verify JWT token using local public key validation (RS256).

    This validates the token signature, expiration, and issuer without
    making a network call to the auth provider. Faster but requires
    keeping the public key in sync.

    Args:
        token: JWT token string

    Returns:
        Decoded token claims if valid, None if invalid

    Example:
        claims = await _verify_token_local(token)
        if claims:
            user_id = claims["sub"]
    """
    if settings.auth_provider_type == AuthProviderType.NONE:
        return None

    if not settings.jwt_public_key:
        context = get_logging_context()
        LOGGER.warning(
            "jwt_public_key_not_configured",
            extra={
                **context,
                "detail": "Cannot validate tokens locally without JWT_PUBLIC_KEY",
            },
        )
        return None

    try:
        # Decode and verify JWT
        decoded = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.auth_provider_issuer,
            leeway=TOKEN_EXPIRY_LEEWAY_SECONDS,
        )
    except jwt.ExpiredSignatureError:
        context = get_logging_context()
        LOGGER.info("token_expired", extra=context)
        return None
    except jwt.InvalidTokenError:
        context = get_logging_context()
        context["validation_method"] = "local"
        LOGGER.info("invalid_token", extra=context, exc_info=True)
        return None
    except Exception:
        context = get_logging_context()
        context["validation_method"] = "local"
        LOGGER.error("token_validation_error", extra=context, exc_info=True)
        return None

    # Log successful validation
    context = get_logging_context()
    context.update({"validation_method": "local", "subject": decoded.get("sub")})
    LOGGER.info("token_validated", extra=context)
    return decoded


async def get_jwks_cached(jwks_url: str) -> dict[str, Any]:
    """Fetch JWKS (JSON Web Key Set) with caching.

    Caches JWKS for 1 hour to avoid fetching on every request. This significantly
    improves performance for providers that use JWKS (Cognito, Auth0, etc.).

    Cache is invalidated if:
    - TTL expires (1 hour)
    - URL changes (different provider configured)

    Args:
        jwks_url: URL to fetch JWKS from (e.g., https://cognito-idp.../jwks.json)

    Returns:
        JWKS as a dictionary containing 'keys' array

    Raises:
        httpx.RequestError: If JWKS fetch fails
        httpx.HTTPStatusError: If JWKS endpoint returns non-200 status

    Example:
        jwks_url = f"{settings.auth_provider_url}/.well-known/jwks.json"
        jwks = await get_jwks_cached(jwks_url)
        # Use jwks['keys'] to find matching key for JWT 'kid' header
    """
    global _jwks_cache, _jwks_cache_url, _jwks_cache_expires  # noqa: PLW0603

    now = datetime.now(UTC)

    # Return cached JWKS if valid
    if (
        _jwks_cache is not None
        and _jwks_cache_url == jwks_url
        and _jwks_cache_expires is not None
        and now < _jwks_cache_expires
    ):
        context = get_logging_context()
        LOGGER.debug("jwks_cache_hit", extra={**context, "jwks_url": jwks_url})
        return _jwks_cache

    # Fetch fresh JWKS
    context = get_logging_context()
    LOGGER.info("jwks_cache_miss", extra={**context, "jwks_url": jwks_url})

    async with http_client(timeout=10.0) as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        jwks = response.json()

    # Update cache
    _jwks_cache = jwks
    _jwks_cache_url = jwks_url
    _jwks_cache_expires = now + timedelta(seconds=JWKS_CACHE_TTL_SECONDS)

    context = get_logging_context()
    LOGGER.info(
        "jwks_cached",
        extra={
            **context,
            "jwks_url": jwks_url,
            "key_count": len(jwks.get("keys", [])),
            "expires_at": _jwks_cache_expires.isoformat(),
        },
    )

    return jwks


def clear_jwks_cache() -> None:
    """Clear the JWKS cache.

    Useful for testing or when you need to force a refresh.
    """
    global _jwks_cache, _jwks_cache_url, _jwks_cache_expires  # noqa: PLW0603
    _jwks_cache = None
    _jwks_cache_url = None
    _jwks_cache_expires = None


async def _verify_token_remote_ory(token: str) -> dict[str, Any] | None:
    """Verify token by calling Ory Hydra introspection endpoint.

    Ory pattern: POST to /oauth2/introspect with token

    Args:
        token: JWT token string

    Returns:
        Token claims if valid, None if invalid

    Example Ory configuration:
        AUTH_PROVIDER_TYPE=ory
        AUTH_PROVIDER_URL=https://your-ory-instance.com
        AUTH_PROVIDER_ISSUER=https://your-ory-instance.com/
    """
    if not settings.auth_provider_url:
        context = get_logging_context()
        LOGGER.warning(
            "auth_provider_url_not_configured",
            extra={**context, "provider": "ory"},
        )
        return None

    introspection_url = f"{settings.auth_provider_url}/oauth2/introspect"

    try:
        async with http_client(timeout=5.0) as client:
            response = await client.post(
                introspection_url,
                data={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != SUCCESSFUL_HTTP_STATUS:
                context = get_logging_context()
                context["status_code"] = str(response.status_code)
                LOGGER.info(
                    "ory_introspection_failed",
                    extra=context,
                )
                return None

            data = response.json()
            if not data.get("active"):
                context = get_logging_context()
                context["provider"] = "ory"
                LOGGER.info("token_not_active", extra=context)
                return None

            context = get_logging_context()
            context.update({"validation_method": "ory", "subject": data.get("sub")})
            LOGGER.info("token_validated", extra=context)
            return data
    except httpx.RequestError:
        context = get_logging_context()
        context["introspection_url"] = introspection_url
        LOGGER.error(
            "ory_connection_failed",
            extra=context,
            exc_info=True,
        )
        return None


async def _verify_token_remote_auth0(token: str) -> dict[str, Any] | None:
    """Verify token by calling Auth0 userinfo endpoint.

    Auth0 pattern: GET /userinfo with Bearer token

    Args:
        token: JWT token string

    Returns:
        Token claims if valid, None if invalid

    Example Auth0 configuration:
        AUTH_PROVIDER_TYPE=auth0
        AUTH_PROVIDER_URL=https://your-tenant.auth0.com
        AUTH_PROVIDER_ISSUER=https://your-tenant.auth0.com/
        JWT_PUBLIC_KEY=<your-auth0-public-key>
    """
    if not settings.auth_provider_url:
        context = get_logging_context()
        LOGGER.warning(
            "auth_provider_url_not_configured",
            extra={**context, "provider": "auth0"},
        )
        return None

    userinfo_url = f"{settings.auth_provider_url}/userinfo"

    try:
        async with http_client(timeout=5.0) as client:
            response = await client.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {token}"},
            )

            if response.status_code != SUCCESSFUL_HTTP_STATUS:
                context = get_logging_context()
                context["status_code"] = str(response.status_code)
                LOGGER.info(
                    "auth0_userinfo_failed",
                    extra=context,
                )
                return None

            data = response.json()
            context = get_logging_context()
            context.update({"validation_method": "auth0", "subject": data.get("sub")})
            LOGGER.info("token_validated", extra=context)
            return data
    except httpx.RequestError:
        context = get_logging_context()
        LOGGER.error(
            "auth0_connection_failed",
            extra={**context, "userinfo_url": userinfo_url},
            exc_info=True,
        )
        return None


async def _verify_token_remote_keycloak(token: str) -> dict[str, Any] | None:
    """Verify token by calling Keycloak introspection endpoint.

    Keycloak pattern: POST to /protocol/openid-connect/token/introspect

    Args:
        token: JWT token string

    Returns:
        Token claims if valid, None if invalid

    Example Keycloak configuration:
        AUTH_PROVIDER_TYPE=keycloak
        AUTH_PROVIDER_URL=https://keycloak.example.com/realms/your-realm
        AUTH_PROVIDER_ISSUER=https://keycloak.example.com/realms/your-realm
        JWT_PUBLIC_KEY=<your-keycloak-public-key>
    """
    if not settings.auth_provider_url:
        context = get_logging_context()
        LOGGER.warning(
            "auth_provider_url_not_configured",
            extra={**context, "provider": "keycloak"},
        )
        return None

    introspection_url = f"{settings.auth_provider_url}/protocol/openid-connect/token/introspect"

    try:
        async with http_client(timeout=5.0) as client:
            response = await client.post(
                introspection_url,
                data={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != SUCCESSFUL_HTTP_STATUS:
                context = get_logging_context()
                context["status_code"] = str(response.status_code)
                LOGGER.info(
                    "keycloak_introspection_failed",
                    extra=context,
                )
                return None

            data = response.json()
            if not data.get("active"):
                context = get_logging_context()
                context["provider"] = "keycloak"
                LOGGER.info("token_not_active", extra=context)
                return None

            context = get_logging_context()
            context.update({"validation_method": "keycloak", "subject": data.get("sub")})
            LOGGER.info("token_validated", extra=context)
            return data
    except httpx.RequestError:
        context = get_logging_context()
        LOGGER.error(
            "keycloak_connection_failed",
            extra={**context, "introspection_url": introspection_url},
            exc_info=True,
        )
        return None


async def _fetch_jwks_for_cognito(jwks_url: str) -> JWKSFetchResult:
    """Fetch JWKS from Cognito with error handling.

    Args:
        jwks_url: URL to fetch JWKS from

    Returns:
        JWKSFetchResult with success status and JWKS or error info
    """
    try:
        jwks = await get_jwks_cached(jwks_url)
        return JWKSFetchResult(success=True, jwks=jwks)
    except httpx.RequestError:
        context = get_logging_context()
        LOGGER.exception(
            "cognito_jwks_fetch_failed",
            extra={**context, "jwks_url": jwks_url},
        )
        return JWKSFetchResult(success=False, error_type="request_error")
    except httpx.HTTPStatusError as e:
        context = get_logging_context()
        LOGGER.warning(
            "cognito_jwks_status_error",
            extra={**context, "jwks_url": jwks_url, "status_code": e.response.status_code},
        )
        return JWKSFetchResult(success=False, error_type="http_status_error")


def _extract_token_kid(token: str) -> TokenHeaderResult:
    """Extract key ID (kid) from JWT token header.

    Args:
        token: JWT token string

    Returns:
        TokenHeaderResult with success status and kid or error info
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            context = get_logging_context()
            LOGGER.warning("cognito_token_missing_kid", extra=context)
            return TokenHeaderResult(success=False, error_type="missing_kid")
        return TokenHeaderResult(success=True, kid=kid)
    except jwt.DecodeError:
        context = get_logging_context()
        LOGGER.warning("cognito_token_decode_error", extra=context)
        return TokenHeaderResult(success=False, error_type="decode_error")


def _find_public_key_in_jwks(jwks: dict[str, Any], kid: str) -> "RSAPublicKey | None":
    """Find and parse public key from JWKS by key ID.

    Args:
        jwks: JWKS dictionary containing keys array
        kid: Key ID to search for

    Returns:
        RSA public key object if found and parseable, None otherwise.
    """
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            try:
                # JWKS keys from auth providers are always public keys
                return jwt.algorithms.RSAAlgorithm.from_jwk(key)  # type: ignore[return-value]
            except (ValueError, KeyError):
                context = get_logging_context()
                LOGGER.warning(
                    "cognito_jwk_parse_error",
                    extra={**context, "kid": kid},
                    exc_info=True,
                )
                continue

    context = get_logging_context()
    available_kids = [k.get("kid") for k in jwks.get("keys", [])]
    LOGGER.warning(
        "cognito_key_not_found",
        extra={**context, "kid": kid, "available_kids": available_kids},
    )
    return None


def _decode_jwt_with_key(token: str, public_key: "RSAPublicKey") -> dict[str, Any] | None:
    """Decode and verify JWT token with public key.

    Args:
        token: JWT token string
        public_key: RSA public key for verification (from jwt.algorithms.RSAAlgorithm.from_jwk)

    Returns:
        Decoded claims if valid, None if invalid
    """
    try:
        decoded = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=settings.auth_provider_issuer,
            leeway=TOKEN_EXPIRY_LEEWAY_SECONDS,
        )
    except jwt.ExpiredSignatureError:
        context = get_logging_context()
        LOGGER.info("cognito_token_expired", extra=context)
        return None
    except jwt.InvalidTokenError:
        context = get_logging_context()
        LOGGER.info("cognito_token_invalid", extra=context, exc_info=True)
        return None
    else:
        context = get_logging_context()
        context.update({"validation_method": "cognito_jwks", "subject": decoded.get("sub")})
        LOGGER.info("token_validated", extra=context)
        return decoded


async def _verify_token_remote_cognito(token: str) -> dict[str, Any] | None:
    """Verify token using AWS Cognito JWKS.

    AWS Cognito uses JWT validation with JWKS (JSON Web Key Set).
    This implementation fetches and caches JWKS for production use.

    Args:
        token: JWT token string

    Returns:
        Token claims if valid, None if invalid

    Example AWS Cognito configuration:
        AUTH_PROVIDER_TYPE=cognito
        AUTH_PROVIDER_URL=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXX
        AUTH_PROVIDER_ISSUER=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXX
        # JWT_PUBLIC_KEY not needed - keys fetched from JWKS endpoint

    JWKS endpoint pattern:
        {AUTH_PROVIDER_URL}/.well-known/jwks.json
    """
    if not settings.auth_provider_url:
        context = get_logging_context()
        LOGGER.warning(
            "auth_provider_url_not_configured",
            extra={**context, "provider": "cognito"},
        )
        return None

    # If JWT_PUBLIC_KEY is configured, use local validation (faster)
    if settings.jwt_public_key:
        return await _verify_token_local(token)

    # Fetch JWKS for key lookup
    jwks_url = f"{settings.auth_provider_url}/.well-known/jwks.json"
    jwks_result = await _fetch_jwks_for_cognito(jwks_url)
    if not jwks_result.success or jwks_result.jwks is None:
        return None

    # Extract key ID from token header
    header_result = _extract_token_kid(token)
    if not header_result.success or header_result.kid is None:
        return None

    # Find matching public key in JWKS
    public_key = _find_public_key_in_jwks(jwks_result.jwks, header_result.kid)
    if public_key is None:
        return None

    # Verify and decode token
    return _decode_jwt_with_key(token, public_key)


async def verify_token(token: str) -> dict[str, Any] | None:
    """Verify JWT token and return decoded claims.

    This is the main entry point for token validation. It supports both
    local validation (using public key) and remote validation (calling
    provider introspection endpoints).

    Validation strategy:
    1. Try local validation if JWT_PUBLIC_KEY is configured (faster)
    2. Fall back to remote validation based on AUTH_PROVIDER_TYPE
    3. Return None if all validation methods fail

    Args:
        token: JWT token string from Authorization header

    Returns:
        Decoded token claims if valid, None if invalid

    Example:
        claims = await verify_token(token)
        if not claims:
            raise HTTPException(status_code=401, detail="Invalid token")

        user_id = claims["sub"]
        email = claims.get("email")
    """
    if settings.auth_provider_type == AuthProviderType.NONE:
        context = get_logging_context()
        LOGGER.debug("auth_disabled", extra={**context, "auth_provider_type": "none"})
        return None

    # Try local validation first (faster, no network call)
    if settings.jwt_public_key:
        claims = await _verify_token_local(token)
        if claims:
            return claims

    # Fall back to remote validation based on provider
    provider_validators = {
        AuthProviderType.ORY: _verify_token_remote_ory,
        AuthProviderType.AUTH0: _verify_token_remote_auth0,
        AuthProviderType.KEYCLOAK: _verify_token_remote_keycloak,
        AuthProviderType.COGNITO: _verify_token_remote_cognito,
    }
    validator = provider_validators.get(AuthProviderType(settings.auth_provider_type))
    if validator:
        return await validator(token)

    context = get_logging_context()
    LOGGER.warning(
        "no_validation_method_succeeded",
        extra={**context, "auth_provider_type": settings.auth_provider_type},
    )
    return None


def _extract_user_from_claims(claims: dict[str, Any]) -> CurrentUser:
    """Extract CurrentUser from JWT claims.

    Maps standard JWT claims and custom claims to CurrentUser model.
    Handles different claim formats from various auth providers.

    Args:
        claims: Decoded JWT claims

    Returns:
        CurrentUser instance

    Raises:
        TokenValidationError: If required claims are missing or invalid
    """
    # Standard 'sub' claim for user ID
    user_id_str = claims.get("sub")
    if not user_id_str:
        msg = "Missing 'sub' claim in token"
        raise TokenValidationError(msg)

    try:
        user_id = UUID(user_id_str)
    except (ValueError, TypeError) as err:
        msg = "Invalid user ID format in 'sub' claim"
        raise TokenValidationError(msg) from err

    # Email claim (standard or custom)
    email = claims.get("email") or claims.get("preferred_username")
    if not email:
        msg = "Missing email claim in token"
        raise TokenValidationError(msg)

    # Organization/tenant ID (custom claim)
    org_id: UUID | None = None
    org_id_str = claims.get("org_id") or claims.get("organization_id")
    if org_id_str:
        try:
            org_id = UUID(org_id_str)
        except (ValueError, TypeError):
            context = get_logging_context()
            LOGGER.warning(
                "invalid_organization_id_format",
                extra={**context, "org_id_str": org_id_str},
            )

    return CurrentUser(id=user_id, email=email, organization_id=org_id)


class AuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for JWT authentication.

    This middleware:
    1. Extracts Bearer token from Authorization header
    2. Validates token using verify_token()
    3. Adds user context to request.state for logging
    4. Returns 401 for invalid/missing tokens (configurable per endpoint)

    Public endpoints (no auth required) can be configured in settings
    or by using the optional dependency injection pattern.

    Usage in main.py:
        from redact_api.core.auth import AuthMiddleware
        app.add_middleware(AuthMiddleware)
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Process request and validate authentication.

        Args:
            request: FastAPI Request object
            call_next: Next middleware in chain

        Returns:
            Response from downstream middleware/endpoint
        """
        # Extract Authorization header
        auth_header = request.headers.get(AUTHORIZATION_HEADER)
        token = _extract_bearer_token(auth_header)

        # If auth is disabled, skip validation
        if settings.auth_provider_type == AuthProviderType.NONE:
            request.state.user = None
            return await call_next(request)

        # Public endpoints don't require authentication
        # Customize this list based on your needs
        public_paths = ["/health", "/ping", "/docs", "/openapi.json", "/metrics"]
        if any(request.url.path.startswith(path) for path in public_paths):
            request.state.user = None
            return await call_next(request)

        # Validate token
        if not token:
            msg = "Missing or invalid Authorization header"
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": msg},
            )

        claims = await verify_token(token)
        if not claims:
            msg = "Invalid or expired token"
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": msg},
            )

        # Extract user from claims
        try:
            current_user = _extract_user_from_claims(claims)
            request.state.user = current_user

            # Log authentication success with user context
            context = get_logging_context()
            LOGGER.debug(
                "user_authenticated",
                extra={
                    **context,
                    "user_id": str(current_user.id),
                    "email": current_user.email,
                    "organization_id": (str(current_user.organization_id) if current_user.organization_id else None),
                },
            )
        except TokenValidationError as err:
            context = get_logging_context()
            context["error"] = str(err)
            LOGGER.warning("token_validation_failed", extra=context)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": str(err)},
            )

        return await call_next(request)


def get_current_user(request: Request) -> CurrentUser:
    """Dependency for endpoints that require authentication.

    Extracts CurrentUser from request.state (populated by AuthMiddleware).
    Raises 401 if user is not authenticated.

    Args:
        request: FastAPI Request object

    Returns:
        CurrentUser instance

    Raises:
        HTTPException: 401 if user not authenticated

    Example:
        from redact_api.core.auth import CurrentUserDep

        @router.get("/protected")
        async def protected_endpoint(current_user: CurrentUserDep) -> dict:
            return {"user_id": current_user.id}
    """
    user = getattr(request.state, "user", None)
    if not user:
        msg = "Authentication required"
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)
    return user


def get_current_user_optional(request: Request) -> CurrentUser | None:
    """Dependency for endpoints with optional authentication.

    Returns CurrentUser if authenticated, None otherwise.
    Does not raise exceptions - allows public access.

    Args:
        request: FastAPI Request object

    Returns:
        CurrentUser if authenticated, None otherwise

    Example:
        from typing import Annotated
        from fastapi import Depends
        from redact_api.core.auth import get_current_user_optional, CurrentUser

        @router.get("/public")
        async def public_endpoint(
            current_user: Annotated[
                CurrentUser | None, Depends(get_current_user_optional)
            ]
        ) -> dict:
            if current_user:
                return {"message": f"Hello {current_user.email}"}
            return {"message": "Hello anonymous user"}
    """
    return getattr(request.state, "user", None)


def _parse_user_headers(
    x_user_id: Annotated[str | None, Header()] = None,
    x_email: Annotated[str | None, Header()] = None,
    x_selected_org: Annotated[str | None, Header()] = None,
) -> tuple[UUID, str, UUID | None]:
    """Parse and validate Oathkeeper headers (format only, no DB validation).

    Args:
        x_user_id: User ID from X-User-ID header
        x_email: Email from X-Email header
        x_selected_org: Organization ID from X-Selected-Org header

    Returns:
        Tuple of (user_id, email, organization_id)

    Raises:
        HTTPException: 401 if headers missing, 400 if IDs have invalid format
    """
    if not x_user_id or not x_email:
        msg = "Missing required authentication headers (X-User-ID, X-Email)"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=msg,
        )

    try:
        user_id = UUID(x_user_id)
    except ValueError as err:
        msg = f"Invalid user ID format: {x_user_id}"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        ) from err

    organization_id: UUID | None = None
    if x_selected_org:
        try:
            organization_id = UUID(x_selected_org)
        except ValueError as err:
            msg = f"Invalid organization ID format: {x_selected_org}"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=msg,
            ) from err

    return user_id, x_email, organization_id


async def get_user_from_headers(
    parsed_headers: Annotated[tuple[UUID, str, UUID | None], Depends(_parse_user_headers)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CurrentUser:
    """Extract user from Oathkeeper headers with organization membership validation.

    Phase 4: Validates organization membership in backend.

    CRITICAL SECURITY: Oathkeeper only validates authentication (user is logged in).
    It does NOT validate organization membership. A malicious user could set
    X-Selected-Org to any UUID and access other orgs' data without backend validation.

    Security Model:
    - X-User-ID and X-Email are trusted from Oathkeeper (validated by Kratos)
    - X-Selected-Org is validated against database (user MUST be organization member)

    Oathkeeper provides these headers:
    - X-User-ID: User's identity ID from Kratos (trusted)
    - X-Email: User's email address (trusted)
    - X-Selected-Org: Organization ID from client (MUST BE VALIDATED)

    Args:
        parsed_headers: Parsed headers from _parse_user_headers dependency
        session: Database session for membership validation

    Returns:
        CurrentUser instance with id, email, and organization_id

    Raises:
        HTTPException: 403 if user is not a member of selected organization
    """
    user_id, email, organization_id = parsed_headers

    # Validate organization membership if org is selected
    if organization_id is not None:
        # CRITICAL: Validate user is actually a member of this organization
        is_member = await is_user_member(session, user_id, organization_id)
        if not is_member:
            msg = "User is not a member of the selected organization"
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=msg,
            )

        # Log organization selection for audit trail (debug level to reduce noise)
        LOGGER.debug(
            "organization_selected",
            extra={
                "user_id": str(user_id),
                "organization_id": str(organization_id),
                "source": "X-Selected-Org",
            },
        )

    return CurrentUser(
        id=user_id,
        email=email,
        organization_id=organization_id,
    )


# Type alias for dependency injection
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
CurrentUserFromHeaders = Annotated[CurrentUser, Depends(get_user_from_headers)]
