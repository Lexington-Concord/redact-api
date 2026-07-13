"""Unit tests for tenant isolation module.

Tests the individual functions and middleware components:
- TenantContext model
- Org ID extraction helpers
- Tenant context validation
- TenantIsolationMiddleware
- validate_tenant_ownership
- get_tenant_context dependency
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.datastructures import QueryParams
from starlette.responses import JSONResponse

from redact_api.core.tenants import (
    TenantContext,
    TenantIsolationMiddleware,
    _extract_org_id_from_jwt,
    _extract_org_id_from_path,
    _extract_org_id_from_query,
    _validate_tenant_context,
    _validate_user_org_access,
    get_tenant_context,
    validate_tenant_ownership,
)
from redact_api.models.membership import Membership, MembershipRole
from redact_api.models.organization import Organization
from redact_api.models.user import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# Test UUIDs
TEST_USER_ID = UUID("12345678-1234-5678-1234-567812345678")
TEST_ORG_ID = UUID("87654321-4321-8765-4321-876543218765")
OTHER_ORG_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


class TestTenantContext:
    """Tests for TenantContext model."""

    def test_create_tenant_context(self) -> None:
        """Should create TenantContext with required fields."""
        context = TenantContext(
            organization_id=TEST_ORG_ID,
            user_id=TEST_USER_ID,
            role=MembershipRole.MEMBER,
        )
        assert context.organization_id == TEST_ORG_ID
        assert context.user_id == TEST_USER_ID
        assert context.role == MembershipRole.MEMBER

    def test_is_isolated_with_valid_ids(self) -> None:
        """Should return True when org_id and user_id are set."""
        context = TenantContext(
            organization_id=TEST_ORG_ID,
            user_id=TEST_USER_ID,
            role=MembershipRole.ADMIN,
        )
        assert context.is_isolated is True

    def test_is_isolated_property(self) -> None:
        """is_isolated should check both organization_id and user_id."""
        # The model requires both fields, so is_isolated should always be True
        # for a valid TenantContext
        context = TenantContext(
            organization_id=TEST_ORG_ID,
            user_id=TEST_USER_ID,
            role=MembershipRole.OWNER,
        )
        assert context.is_isolated is True


class TestValidateUserOrgAccess:
    """Tests for _validate_user_org_access helper."""

    @pytest.mark.asyncio
    async def test_user_with_membership_returns_true_and_role(self, session: AsyncSession) -> None:
        """Should return (True, role) when user is a member."""
        # Create test data
        org = Organization(name="Test Org")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        user = User(name="Test User", email="test@example.com")
        session.add(user)
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(
            user_id=user.id,
            organization_id=org.id,
            role=MembershipRole.ADMIN,
        )
        session.add(membership)
        await session.commit()

        has_access, role = await _validate_user_org_access(session, user.id, org.id)
        assert has_access is True
        assert role == MembershipRole.ADMIN

    @pytest.mark.asyncio
    async def test_user_without_membership_returns_false_and_none(self, session: AsyncSession) -> None:
        """Should return (False, None) when user is not a member."""
        org = Organization(name="Test Org No Member")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        user = User(name="Non Member", email="nonmember@example.com")
        session.add(user)
        await session.commit()

        has_access, role = await _validate_user_org_access(session, user.id, org.id)
        assert has_access is False
        assert role is None

    @pytest.mark.asyncio
    async def test_nonexistent_user_returns_false(self, session: AsyncSession) -> None:
        """Should return (False, None) for nonexistent user."""
        org = Organization(name="Test Org Nonexistent User")
        session.add(org)
        await session.commit()

        has_access, role = await _validate_user_org_access(session, uuid4(), org.id)
        assert has_access is False
        assert role is None


class TestExtractOrgIdFromJwt:
    """Tests for _extract_org_id_from_jwt helper."""

    def test_extracts_org_id_from_user_with_organization_id(self) -> None:
        """Should extract organization_id from user object."""
        mock_user = MagicMock()
        mock_user.organization_id = TEST_ORG_ID

        result = _extract_org_id_from_jwt(mock_user)
        assert result == TEST_ORG_ID

    def test_returns_none_when_no_organization_id(self) -> None:
        """Should return None when user has no organization_id."""
        mock_user = MagicMock()
        mock_user.organization_id = None

        result = _extract_org_id_from_jwt(mock_user)
        assert result is None

    def test_returns_none_when_no_attribute(self) -> None:
        """Should return None when user lacks organization_id attribute."""
        mock_user = MagicMock(spec=[])  # No attributes
        del mock_user.organization_id  # Ensure attribute doesn't exist

        result = _extract_org_id_from_jwt(mock_user)
        assert result is None


class TestExtractOrgIdFromPath:
    """Tests for _extract_org_id_from_path helper."""

    def test_extracts_org_id_from_path_params(self) -> None:
        """Should extract org_id from path parameters."""
        mock_request = MagicMock()
        mock_request.path_params = {"org_id": str(TEST_ORG_ID)}

        org_id, error = _extract_org_id_from_path(mock_request)
        assert org_id == TEST_ORG_ID
        assert error is None

    def test_returns_none_when_no_org_id_in_path(self) -> None:
        """Should return (None, None) when org_id not in path."""
        mock_request = MagicMock()
        mock_request.path_params = {}

        org_id, error = _extract_org_id_from_path(mock_request)
        assert org_id is None
        assert error is None

    def test_returns_error_response_for_invalid_uuid(self) -> None:
        """Should return error response for invalid UUID format."""
        mock_request = MagicMock()
        mock_request.path_params = {"org_id": "not-a-uuid"}

        org_id, error = _extract_org_id_from_path(mock_request)
        assert org_id is None
        assert isinstance(error, JSONResponse)
        assert error.status_code == 400

    def test_returns_error_response_for_malformed_uuid(self) -> None:
        """Should return error for malformed UUID."""
        mock_request = MagicMock()
        mock_request.path_params = {"org_id": "12345"}  # Too short

        org_id, error = _extract_org_id_from_path(mock_request)
        assert org_id is None
        assert isinstance(error, JSONResponse)


class TestExtractOrgIdFromQuery:
    """Tests for _extract_org_id_from_query helper."""

    def test_extracts_org_id_from_query_params(self) -> None:
        """Should extract org_id from query parameters."""
        mock_request = MagicMock()
        mock_request.query_params = QueryParams({"org_id": str(TEST_ORG_ID)})

        org_id, error = _extract_org_id_from_query(mock_request)
        assert org_id == TEST_ORG_ID
        assert error is None

    def test_returns_none_when_no_org_id_in_query(self) -> None:
        """Should return (None, None) when org_id not in query."""
        mock_request = MagicMock()
        mock_request.query_params = QueryParams({})

        org_id, error = _extract_org_id_from_query(mock_request)
        assert org_id is None
        assert error is None

    def test_returns_error_response_for_invalid_uuid(self) -> None:
        """Should return error response for invalid UUID format."""
        mock_request = MagicMock()
        mock_request.query_params = QueryParams({"org_id": "invalid-uuid"})

        org_id, error = _extract_org_id_from_query(mock_request)
        assert org_id is None
        assert isinstance(error, JSONResponse)
        assert error.status_code == 400


class TestValidateTenantContext:
    """Tests for _validate_tenant_context helper."""

    @pytest.mark.asyncio
    async def test_validates_with_jwt_org_id(self, session: AsyncSession) -> None:
        """Should validate tenant context from JWT claims."""
        # Create test data
        org = Organization(name="Validate JWT Org")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        user = User(name="JWT User", email="jwt@example.com")
        session.add(user)
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(
            user_id=user.id,
            organization_id=org.id,
            role=MembershipRole.MEMBER,
        )
        session.add(membership)
        await session.commit()

        mock_request = MagicMock()
        mock_request.path_params = {}
        mock_request.query_params = QueryParams({})

        mock_user = MagicMock()
        mock_user.id = user.id
        mock_user.organization_id = org.id

        tenant, error = await _validate_tenant_context(mock_request, mock_user, session)

        assert error is None
        assert tenant is not None
        assert tenant.organization_id == org.id
        assert tenant.user_id == user.id
        assert tenant.role == MembershipRole.MEMBER

    @pytest.mark.asyncio
    async def test_validates_with_path_org_id(self, session: AsyncSession) -> None:
        """Should validate tenant context from path parameters."""
        org = Organization(name="Path Org")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        user = User(name="Path User", email="path@example.com")
        session.add(user)
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(
            user_id=user.id,
            organization_id=org.id,
            role=MembershipRole.ADMIN,
        )
        session.add(membership)
        await session.commit()

        mock_request = MagicMock()
        mock_request.path_params = {"org_id": str(org.id)}
        mock_request.query_params = QueryParams({})

        mock_user = MagicMock()
        mock_user.id = user.id
        mock_user.organization_id = None  # No JWT claim

        tenant, error = await _validate_tenant_context(mock_request, mock_user, session)

        assert error is None
        assert tenant is not None
        assert tenant.organization_id == org.id

    @pytest.mark.asyncio
    async def test_validates_with_query_org_id(self, session: AsyncSession) -> None:
        """Should validate tenant context from query parameters."""
        org = Organization(name="Query Org")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        user = User(name="Query User", email="query@example.com")
        session.add(user)
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(
            user_id=user.id,
            organization_id=org.id,
            role=MembershipRole.OWNER,
        )
        session.add(membership)
        await session.commit()

        mock_request = MagicMock()
        mock_request.path_params = {}
        mock_request.query_params = QueryParams({"org_id": str(org.id)})

        mock_user = MagicMock()
        mock_user.id = user.id
        mock_user.organization_id = None

        tenant, error = await _validate_tenant_context(mock_request, mock_user, session)

        assert error is None
        assert tenant is not None
        assert tenant.organization_id == org.id

    @pytest.mark.asyncio
    async def test_returns_error_when_no_org_id(self) -> None:
        """Should return 403 when no organization ID is found."""
        mock_request = MagicMock()
        mock_request.path_params = {}
        mock_request.query_params = QueryParams({})

        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user.organization_id = None

        tenant, error = await _validate_tenant_context(mock_request, mock_user)

        assert tenant is None
        assert isinstance(error, JSONResponse)
        assert error.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_error_when_user_not_member(self, session: AsyncSession) -> None:
        """Should return 403 when user is not a member of org."""
        org = Organization(name="No Access Org")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        user = User(name="No Access User", email="noaccess@example.com")
        session.add(user)
        await session.commit()

        mock_request = MagicMock()
        mock_request.path_params = {"org_id": str(org.id)}
        mock_request.query_params = QueryParams({})

        mock_user = MagicMock()
        mock_user.id = user.id
        mock_user.organization_id = None

        tenant, error = await _validate_tenant_context(mock_request, mock_user, session)

        assert tenant is None
        assert isinstance(error, JSONResponse)
        assert error.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_path_error_when_invalid_path_uuid(self) -> None:
        """Should return 400 when path UUID is invalid."""
        mock_request = MagicMock()
        mock_request.path_params = {"org_id": "not-valid-uuid"}
        mock_request.query_params = QueryParams({})

        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user.organization_id = None

        tenant, error = await _validate_tenant_context(mock_request, mock_user)

        assert tenant is None
        assert isinstance(error, JSONResponse)
        assert error.status_code == 400

    @pytest.mark.asyncio
    async def test_creates_session_when_not_provided(self, session: AsyncSession) -> None:
        """Should create session from app.state when not provided."""
        org = Organization(name="App State Org")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        user = User(name="App State User", email="appstate@example.com")
        session.add(user)
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(
            user_id=user.id,
            organization_id=org.id,
            role=MembershipRole.MEMBER,
        )
        session.add(membership)
        await session.commit()

        # Mock the session maker
        mock_session_maker = MagicMock()
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__ = AsyncMock(return_value=session)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)
        mock_session_maker.return_value = mock_context_manager

        mock_app = MagicMock()
        mock_app.state.async_session_maker = mock_session_maker

        mock_request = MagicMock()
        mock_request.path_params = {"org_id": str(org.id)}
        mock_request.query_params = QueryParams({})
        mock_request.app = mock_app

        mock_user = MagicMock()
        mock_user.id = user.id
        mock_user.organization_id = None

        # Call without session (should use app.state)
        tenant, error = await _validate_tenant_context(mock_request, mock_user)

        assert error is None
        assert tenant is not None
        mock_session_maker.assert_called_once()


class TestTenantIsolationMiddleware:
    """Tests for TenantIsolationMiddleware."""

    @pytest.mark.asyncio
    async def test_skips_public_endpoints(self) -> None:
        """Should skip tenant isolation for public endpoints."""
        middleware = TenantIsolationMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/health"
        mock_request.state = MagicMock()

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response == mock_response
        assert mock_request.state.tenant is None
        mock_call_next.assert_called_once_with(mock_request)

    @pytest.mark.asyncio
    async def test_skips_when_enforcement_disabled(self) -> None:
        """Should skip tenant isolation when enforcement is disabled."""
        middleware = TenantIsolationMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/api/resources"
        mock_request.state = MagicMock()

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)

        with patch("redact_api.core.tenants.settings.enforce_tenant_isolation", False):
            response = await middleware.dispatch(mock_request, mock_call_next)

        assert response == mock_response
        assert mock_request.state.tenant is None

    @pytest.mark.asyncio
    async def test_returns_401_when_no_user(self) -> None:
        """Should return 401 when no authenticated user."""
        middleware = TenantIsolationMiddleware(app=MagicMock())

        mock_state = MagicMock(spec=[])  # No 'user' attribute
        del mock_state.user

        mock_request = MagicMock()
        mock_request.url.path = "/api/resources"
        mock_request.state = mock_state

        mock_call_next = AsyncMock()

        with patch("redact_api.core.tenants.settings.enforce_tenant_isolation", True):
            response = await middleware.dispatch(mock_request, mock_call_next)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 401
        mock_call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_error_from_validation(self) -> None:
        """Should return error response from tenant validation."""
        middleware = TenantIsolationMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/api/resources"
        mock_request.state = MagicMock()
        mock_request.state.user = MagicMock()
        mock_request.state.user.id = TEST_USER_ID
        mock_request.state.user.organization_id = None
        mock_request.path_params = {}
        mock_request.query_params = QueryParams({})

        mock_call_next = AsyncMock()

        with patch("redact_api.core.tenants.settings.enforce_tenant_isolation", True):
            response = await middleware.dispatch(mock_request, mock_call_next)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_sets_tenant_context_on_success(self, session: AsyncSession) -> None:
        """Should set tenant context on request.state on success."""
        org = Organization(name="Middleware Test Org")
        session.add(org)
        await session.flush()  # type: ignore[attr-defined]

        user = User(name="Middleware User", email="middleware@example.com")
        session.add(user)
        await session.flush()  # type: ignore[attr-defined]

        membership = Membership(
            user_id=user.id,
            organization_id=org.id,
            role=MembershipRole.MEMBER,
        )
        session.add(membership)
        await session.commit()

        middleware = TenantIsolationMiddleware(app=MagicMock())

        # Mock session maker
        mock_session_maker = MagicMock()
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__ = AsyncMock(return_value=session)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)
        mock_session_maker.return_value = mock_context_manager

        mock_app = MagicMock()
        mock_app.state.async_session_maker = mock_session_maker

        mock_state = MagicMock()
        mock_state.user = MagicMock()
        mock_state.user.id = user.id
        mock_state.user.organization_id = org.id

        mock_request = MagicMock()
        mock_request.url.path = "/api/resources"
        mock_request.state = mock_state
        mock_request.path_params = {}
        mock_request.query_params = QueryParams({})
        mock_request.app = mock_app

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)

        with patch("redact_api.core.tenants.settings.enforce_tenant_isolation", True):
            response = await middleware.dispatch(mock_request, mock_call_next)

        assert response == mock_response
        assert mock_request.state.tenant is not None
        assert mock_request.state.tenant.organization_id == org.id


class TestGetTenantContext:
    """Tests for get_tenant_context dependency."""

    def test_returns_tenant_from_request_state(self) -> None:
        """Should return tenant context from request.state."""
        expected_tenant = TenantContext(
            organization_id=TEST_ORG_ID,
            user_id=TEST_USER_ID,
            role=MembershipRole.ADMIN,
        )

        mock_request = MagicMock()
        mock_request.state.tenant = expected_tenant

        result = get_tenant_context(mock_request)
        assert result == expected_tenant

    def test_raises_401_when_no_tenant(self) -> None:
        """Should raise 401 when tenant context is not available."""
        mock_state = MagicMock(spec=[])  # No 'tenant' attribute
        del mock_state.tenant

        mock_request = MagicMock()
        mock_request.state = mock_state

        with pytest.raises(HTTPException) as exc_info:
            get_tenant_context(mock_request)

        assert exc_info.value.status_code == 401

    def test_raises_401_when_tenant_is_none(self) -> None:
        """Should raise 401 when tenant is None."""
        mock_request = MagicMock()
        mock_request.state.tenant = None

        with pytest.raises(HTTPException) as exc_info:
            get_tenant_context(mock_request)

        assert exc_info.value.status_code == 401


class TestValidateTenantOwnership:
    """Tests for validate_tenant_ownership helper."""

    @pytest.mark.asyncio
    async def test_passes_when_org_id_matches(self, session: AsyncSession) -> None:
        """Should not raise when organization_id matches tenant."""
        tenant = TenantContext(
            organization_id=TEST_ORG_ID,
            user_id=TEST_USER_ID,
            role=MembershipRole.MEMBER,
        )

        # Should not raise
        await validate_tenant_ownership(session, tenant, TEST_ORG_ID)

    @pytest.mark.asyncio
    async def test_raises_403_when_org_id_mismatch(self, session: AsyncSession) -> None:
        """Should raise 403 when organization_id doesn't match tenant."""
        tenant = TenantContext(
            organization_id=TEST_ORG_ID,
            user_id=TEST_USER_ID,
            role=MembershipRole.MEMBER,
        )

        with pytest.raises(HTTPException) as exc_info:
            await validate_tenant_ownership(session, tenant, OTHER_ORG_ID)

        assert exc_info.value.status_code == 403
        assert "different organization" in exc_info.value.detail


class TestPublicEndpoints:
    """Tests for public endpoint handling."""

    @pytest.mark.asyncio
    async def test_docs_endpoint_is_public(self) -> None:
        """Should skip tenant isolation for /docs endpoint."""
        middleware = TenantIsolationMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/docs"
        mock_request.state = MagicMock()

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response == mock_response
        assert mock_request.state.tenant is None

    @pytest.mark.asyncio
    async def test_ping_endpoint_is_public(self) -> None:
        """Should skip tenant isolation for /ping endpoint."""
        middleware = TenantIsolationMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/ping"
        mock_request.state = MagicMock()

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_metrics_endpoint_is_public(self) -> None:
        """Should skip tenant isolation for /metrics endpoint."""
        middleware = TenantIsolationMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/metrics"
        mock_request.state = MagicMock()

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_openapi_endpoint_is_public(self) -> None:
        """Should skip tenant isolation for /openapi.json endpoint."""
        middleware = TenantIsolationMiddleware(app=MagicMock())

        mock_request = MagicMock()
        mock_request.url.path = "/openapi.json"
        mock_request.state = MagicMock()

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(mock_request, mock_call_next)
        assert response == mock_response
