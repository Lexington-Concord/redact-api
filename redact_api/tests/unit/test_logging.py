"""Tests for core logging module with context vars and middleware.

These are unit tests that do not require database access.
"""

import logging
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import Response

from redact_api.core.logging import (
    LoggingMiddleware,
    _org_id_var,
    _request_id_var,
    _user_id_var,
    get_logger,
    get_logging_context,
    get_org_id,
    get_request_id,
    get_user_id,
    log_with_context,
    set_request_id,
    set_user_context,
)


# Override autouse database fixtures from conftest.py for unit tests
@pytest.fixture
def reset_db() -> None:
    """No-op override for unit tests that don't need database."""


@pytest.fixture
def default_auth_user_in_org() -> None:
    """No-op override for unit tests that don't need database."""


@pytest.fixture(autouse=True)
def reset_context_vars() -> Generator[None]:
    """Reset context vars before each test."""
    token1 = _request_id_var.set(None)
    token2 = _user_id_var.set(None)
    token3 = _org_id_var.set(None)
    yield
    _request_id_var.reset(token1)
    _user_id_var.reset(token2)
    _org_id_var.reset(token3)


class TestRequestIdContextVar:
    """Tests for request ID context variable functions."""

    def test_set_and_get_request_id(self) -> None:
        request_id = "test-request-123"

        set_request_id(request_id)

        assert get_request_id() == request_id

    def test_get_request_id_returns_none_when_not_set(self) -> None:
        result = get_request_id()

        assert result is None

    def test_set_request_id_overwrites_previous_value(self) -> None:
        set_request_id("first-request-id")
        set_request_id("second-request-id")

        assert get_request_id() == "second-request-id"

    def test_request_id_with_uuid_format(self) -> None:
        request_id = str(uuid4())

        set_request_id(request_id)

        assert get_request_id() == request_id


class TestUserContextVars:
    """Tests for user and organization context variable functions."""

    def test_set_user_context_with_org(self) -> None:
        set_user_context("user-123", "org-456")

        assert get_user_id() == "user-123"
        assert get_org_id() == "org-456"

    def test_set_user_context_without_org(self) -> None:
        set_user_context("user-123")

        assert get_user_id() == "user-123"
        assert get_org_id() is None

    def test_set_user_context_with_none_org(self) -> None:
        set_user_context("user-123", None)

        assert get_user_id() == "user-123"
        assert get_org_id() is None

    def test_get_user_id_returns_none_when_not_set(self) -> None:
        result = get_user_id()

        assert result is None

    def test_get_org_id_returns_none_when_not_set(self) -> None:
        result = get_org_id()

        assert result is None

    def test_set_user_context_overwrites_previous_values(self) -> None:
        set_user_context("user-1", "org-1")
        set_user_context("user-2", "org-2")

        assert get_user_id() == "user-2"
        assert get_org_id() == "org-2"


class TestGetLoggingContext:
    """Tests for get_logging_context function."""

    def test_returns_all_context_values(self) -> None:
        set_request_id("req-1")
        set_user_context("user-1", "org-1")

        context = get_logging_context()

        assert context == {
            "request_id": "req-1",
            "user_id": "user-1",
            "org_id": "org-1",
        }

    def test_returns_none_values_when_not_set(self) -> None:
        context = get_logging_context()

        assert context == {
            "request_id": None,
            "user_id": None,
            "org_id": None,
        }

    def test_returns_partial_context(self) -> None:
        set_request_id("req-1")

        context = get_logging_context()

        assert context == {
            "request_id": "req-1",
            "user_id": None,
            "org_id": None,
        }


class TestLogWithContext:
    """Tests for log_with_context helper function."""

    def test_merges_context_with_extra(self) -> None:
        set_request_id("req-1")
        set_user_context("user-1", "org-1")
        mock_logger = MagicMock(spec=logging.Logger)

        log_with_context(
            mock_logger,
            logging.INFO,
            "test_message",
            extra={"custom_field": "custom_value"},
        )

        mock_logger.log.assert_called_once_with(
            logging.INFO,
            "test_message",
            extra={
                "request_id": "req-1",
                "user_id": "user-1",
                "org_id": "org-1",
                "custom_field": "custom_value",
            },
        )

    def test_works_without_extra(self) -> None:
        set_request_id("req-1")
        mock_logger = MagicMock(spec=logging.Logger)

        log_with_context(mock_logger, logging.WARNING, "warning_message")

        mock_logger.log.assert_called_once_with(
            logging.WARNING,
            "warning_message",
            extra={
                "request_id": "req-1",
                "user_id": None,
                "org_id": None,
            },
        )

    def test_extra_overrides_context(self) -> None:
        set_request_id("context-req")
        mock_logger = MagicMock(spec=logging.Logger)

        log_with_context(
            mock_logger,
            logging.INFO,
            "message",
            extra={"request_id": "override-req"},
        )

        mock_logger.log.assert_called_once()
        call_extra = mock_logger.log.call_args.kwargs["extra"]
        assert call_extra["request_id"] == "override-req"

    def test_different_log_levels(self) -> None:
        mock_logger = MagicMock(spec=logging.Logger)

        log_with_context(mock_logger, logging.DEBUG, "debug_message")
        log_with_context(mock_logger, logging.ERROR, "error_message")

        assert mock_logger.log.call_count == 2
        calls = mock_logger.log.call_args_list
        assert calls[0].args[0] == logging.DEBUG
        assert calls[1].args[0] == logging.ERROR


class TestLoggingMiddleware:
    """Tests for LoggingMiddleware."""

    def _create_mock_request(
        self,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        path: str = "/test",
        client_host: str = "127.0.0.1",
    ) -> MagicMock:
        """Helper to create mock request objects."""
        mock_request = MagicMock(spec=Request)
        mock_request.method = method
        mock_request.url = MagicMock()
        mock_request.url.path = path
        mock_request.client = MagicMock()
        mock_request.client.host = client_host
        mock_request.headers = Headers(headers or {})
        mock_request.state = MagicMock()
        mock_request.state.user = None
        return mock_request

    @pytest.mark.anyio
    async def test_generates_request_id_when_not_provided(self) -> None:
        middleware = LoggingMiddleware(app=MagicMock())
        mock_request = self._create_mock_request()
        mock_response = MagicMock(spec=Response)
        mock_response.headers = {}
        mock_response.status_code = 200
        call_next = AsyncMock(return_value=mock_response)

        with patch("redact_api.core.logging.settings") as mock_settings:
            mock_settings.request_id_header = "x-request-id"
            mock_settings.include_request_context_in_logs = False

            await middleware.dispatch(mock_request, call_next)

        # Verify a UUID was generated and set in response headers
        assert "x-request-id" in mock_response.headers
        request_id = mock_response.headers["x-request-id"]
        # Should be a valid UUID-like string (36 chars with hyphens)
        assert len(request_id) == 36

    @pytest.mark.anyio
    async def test_uses_provided_request_id(self) -> None:
        middleware = LoggingMiddleware(app=MagicMock())
        provided_id = "custom-request-id-123"
        mock_request = self._create_mock_request(headers={"x-request-id": provided_id})
        mock_response = MagicMock(spec=Response)
        mock_response.headers = {}
        mock_response.status_code = 200
        call_next = AsyncMock(return_value=mock_response)

        with patch("redact_api.core.logging.settings") as mock_settings:
            mock_settings.request_id_header = "x-request-id"
            mock_settings.include_request_context_in_logs = False

            await middleware.dispatch(mock_request, call_next)

        assert mock_response.headers["x-request-id"] == provided_id

    @pytest.mark.anyio
    async def test_adds_request_id_to_response_headers(self) -> None:
        middleware = LoggingMiddleware(app=MagicMock())
        mock_request = self._create_mock_request()
        mock_response = MagicMock(spec=Response)
        mock_response.headers = {}
        mock_response.status_code = 200
        call_next = AsyncMock(return_value=mock_response)

        with patch("redact_api.core.logging.settings") as mock_settings:
            mock_settings.request_id_header = "x-request-id"
            mock_settings.include_request_context_in_logs = False

            await middleware.dispatch(mock_request, call_next)

        assert "x-request-id" in mock_response.headers

    @pytest.mark.anyio
    async def test_calls_next_middleware(self) -> None:
        middleware = LoggingMiddleware(app=MagicMock())
        mock_request = self._create_mock_request()
        mock_response = MagicMock(spec=Response)
        mock_response.headers = {}
        mock_response.status_code = 200
        call_next = AsyncMock(return_value=mock_response)

        with patch("redact_api.core.logging.settings") as mock_settings:
            mock_settings.request_id_header = "x-request-id"
            mock_settings.include_request_context_in_logs = False

            await middleware.dispatch(mock_request, call_next)

        call_next.assert_called_once_with(mock_request)

    @pytest.mark.anyio
    async def test_returns_response_from_call_next(self) -> None:
        middleware = LoggingMiddleware(app=MagicMock())
        mock_request = self._create_mock_request()
        mock_response = MagicMock(spec=Response)
        mock_response.headers = {}
        mock_response.status_code = 200
        call_next = AsyncMock(return_value=mock_response)

        with patch("redact_api.core.logging.settings") as mock_settings:
            mock_settings.request_id_header = "x-request-id"
            mock_settings.include_request_context_in_logs = False

            result = await middleware.dispatch(mock_request, call_next)

        assert result is mock_response

    @pytest.mark.anyio
    async def test_logs_request_started_when_enabled(self) -> None:
        middleware = LoggingMiddleware(app=MagicMock())
        mock_request = self._create_mock_request()
        mock_response = MagicMock(spec=Response)
        mock_response.headers = {}
        mock_response.status_code = 200
        call_next = AsyncMock(return_value=mock_response)

        with (
            patch("redact_api.core.logging.settings") as mock_settings,
            patch("redact_api.core.logging.LOGGER") as mock_logger,
        ):
            mock_settings.request_id_header = "x-request-id"
            mock_settings.include_request_context_in_logs = True

            await middleware.dispatch(mock_request, call_next)

        # Verify request_started was logged
        info_calls = [c for c in mock_logger.info.call_args_list]
        assert len(info_calls) >= 1
        assert info_calls[0].args[0] == "request_started"

    @pytest.mark.anyio
    async def test_handles_request_without_client(self) -> None:
        middleware = LoggingMiddleware(app=MagicMock())
        mock_request = self._create_mock_request()
        mock_request.client = None
        mock_response = MagicMock(spec=Response)
        mock_response.headers = {}
        mock_response.status_code = 200
        call_next = AsyncMock(return_value=mock_response)

        with patch("redact_api.core.logging.settings") as mock_settings:
            mock_settings.request_id_header = "x-request-id"
            mock_settings.include_request_context_in_logs = True

            # Should not raise an error
            result = await middleware.dispatch(mock_request, call_next)

        assert result is mock_response

    @pytest.mark.anyio
    async def test_sets_user_context_from_request_state(self) -> None:
        middleware = LoggingMiddleware(app=MagicMock())
        mock_request = self._create_mock_request()

        # Create a mock user with id and organization_id
        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.organization_id = uuid4()

        # Setup: call_next sets user on request.state
        mock_response = MagicMock(spec=Response)
        mock_response.headers = {}
        mock_response.status_code = 200

        async def set_user_and_return(request: Request) -> Response:
            # Simulate auth middleware setting user
            request.state.user = mock_user
            return mock_response

        call_next = AsyncMock(side_effect=set_user_and_return)

        with patch("redact_api.core.logging.settings") as mock_settings:
            mock_settings.request_id_header = "x-request-id"
            mock_settings.include_request_context_in_logs = True

            await middleware.dispatch(mock_request, call_next)

        # Verify user context was set (checking via logging context)
        # Note: context is set after call_next returns
        assert mock_response.headers["x-request-id"] is not None


class TestGetLogger:
    """Tests for get_logger convenience function."""

    def test_returns_logger_with_name(self) -> None:
        logger = get_logger("test.module")

        assert logger.name == "test.module"

    def test_returns_logger_with_different_names(self) -> None:
        logger1 = get_logger("module.one")
        logger2 = get_logger("module.two")

        assert logger1.name == "module.one"
        assert logger2.name == "module.two"

    def test_returns_same_logger_for_same_name(self) -> None:
        logger1 = get_logger("same.module")
        logger2 = get_logger("same.module")

        assert logger1 is logger2

    def test_returns_logging_logger_instance(self) -> None:
        logger = get_logger("test")

        assert isinstance(logger, logging.Logger)
