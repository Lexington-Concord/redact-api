"""Tests for middleware module.

Tests cover:
- RequestSizeValidationMiddleware (content-length validation, 413 responses)
- RequestLoggingMiddleware (logging of requests, warning for error statuses)

These are unit tests that don't require database access.
"""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from redact_api.core.middleware import (
    MAX_REQUEST_SIZE_BYTES_DEFAULT,
    RequestLoggingMiddleware,
    RequestSizeValidationMiddleware,
)


@pytest.fixture
def app_with_size_middleware() -> FastAPI:
    """Create FastAPI app with RequestSizeValidationMiddleware configured.

    Returns:
        FastAPI app with 1KB size limit for testing.
    """
    app = FastAPI()
    max_size = 1024  # 1KB limit for testing
    app.add_middleware(RequestSizeValidationMiddleware, max_size_bytes=max_size)

    @app.post("/upload")
    async def upload() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    return app


@pytest.fixture
def app_with_logging_middleware() -> FastAPI:
    """Create FastAPI app with RequestLoggingMiddleware configured.

    Returns:
        FastAPI app with logging middleware.
    """
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/test")
    async def test_endpoint() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/error")
    async def error_endpoint() -> JSONResponse:
        return JSONResponse(status_code=HTTPStatus.NOT_FOUND, content={"detail": "not found"})

    @app.get("/server-error")
    async def server_error_endpoint() -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content={"detail": "server error"},
        )

    @app.get("/exception")
    async def exception_endpoint() -> None:
        error_msg = "Test exception"
        raise ValueError(error_msg)

    return app


class TestRequestSizeValidationMiddleware:
    """Tests for request size validation middleware."""

    @pytest.mark.anyio
    async def test_allows_small_request(self, app_with_size_middleware: FastAPI) -> None:
        """Requests under size limit should pass through."""
        async with AsyncClient(
            transport=ASGITransport(app=app_with_size_middleware),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/upload",
                content=b"small",
                headers={"content-length": "5"},
            )

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"status": "ok"}

    @pytest.mark.anyio
    async def test_rejects_oversized_request(
        self,
        app_with_size_middleware: FastAPI,
    ) -> None:
        """Requests exceeding size limit should return 413."""
        async with AsyncClient(
            transport=ASGITransport(app=app_with_size_middleware),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/upload",
                headers={"content-length": "2048"},  # > 1024 limit
            )

        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert "maximum allowed size" in response.json()["detail"]

    @pytest.mark.anyio
    async def test_allows_request_at_exact_limit(
        self,
        app_with_size_middleware: FastAPI,
    ) -> None:
        """Requests exactly at size limit should pass through."""
        async with AsyncClient(
            transport=ASGITransport(app=app_with_size_middleware),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/upload",
                content=b"x" * 1024,  # Exactly 1KB
                headers={"content-length": "1024"},
            )

        assert response.status_code == HTTPStatus.OK

    @pytest.mark.anyio
    async def test_handles_invalid_content_length(
        self,
        app_with_size_middleware: FastAPI,
    ) -> None:
        """Invalid content-length should be passed through to endpoint."""
        async with AsyncClient(
            transport=ASGITransport(app=app_with_size_middleware),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/upload",
                headers={"content-length": "invalid"},
            )

        # Invalid content-length is passed through (endpoint handles it)
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.anyio
    async def test_handles_missing_content_length(
        self,
        app_with_size_middleware: FastAPI,
    ) -> None:
        """Missing content-length header should pass through."""
        async with AsyncClient(
            transport=ASGITransport(app=app_with_size_middleware),
            base_url="http://test",
        ) as client:
            response = await client.get("/health")

        assert response.status_code == HTTPStatus.OK

    @pytest.mark.anyio
    async def test_logs_warning_on_oversized_request(
        self,
        app_with_size_middleware: FastAPI,
    ) -> None:
        """Oversized request should log warning with details."""
        with patch("redact_api.core.middleware.LOGGER") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app_with_size_middleware),
                base_url="http://test",
            ) as client:
                await client.post(
                    "/upload",
                    headers={"content-length": "5000"},
                )

            mock_logger.warning.assert_called_once()
            call_kwargs = mock_logger.warning.call_args
            assert "request_size_exceeded" in str(call_kwargs)

    def test_default_max_size_constant(self) -> None:
        """Default max size should be 50MB."""
        expected_size = 50 * 1024 * 1024
        assert expected_size == MAX_REQUEST_SIZE_BYTES_DEFAULT


class TestRequestLoggingMiddleware:
    """Tests for request logging middleware."""

    @pytest.mark.anyio
    async def test_logs_successful_request(
        self,
        app_with_logging_middleware: FastAPI,
    ) -> None:
        """Successful request should be logged with info level."""
        with patch("redact_api.core.middleware.LOGGER") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app_with_logging_middleware),
                base_url="http://test",
            ) as client:
                await client.get("/test")

            mock_logger.info.assert_called_once()
            call_kwargs = mock_logger.info.call_args
            assert "http_request" in str(call_kwargs)

    @pytest.mark.anyio
    async def test_logs_warning_for_client_error(
        self,
        app_with_logging_middleware: FastAPI,
    ) -> None:
        """Client error (4xx) should be logged with warning level."""
        with patch("redact_api.core.middleware.LOGGER") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app_with_logging_middleware),
                base_url="http://test",
            ) as client:
                await client.get("/error")

            mock_logger.warning.assert_called_once()

    @pytest.mark.anyio
    async def test_logs_warning_for_server_error(
        self,
        app_with_logging_middleware: FastAPI,
    ) -> None:
        """Server error (5xx) should be logged with warning level."""
        with patch("redact_api.core.middleware.LOGGER") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app_with_logging_middleware),
                base_url="http://test",
            ) as client:
                await client.get("/server-error")

            mock_logger.warning.assert_called_once()

    @pytest.mark.anyio
    async def test_logs_exception_on_failure(
        self,
        app_with_logging_middleware: FastAPI,
    ) -> None:
        """Exception during request handling should be logged."""
        with patch("redact_api.core.middleware.LOGGER") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app_with_logging_middleware),
                base_url="http://test",
            ) as client:
                with pytest.raises(Exception):  # noqa: B017, PT011
                    await client.get("/exception")

            mock_logger.exception.assert_called_once()
            call_kwargs = mock_logger.exception.call_args
            assert "request_failed" in str(call_kwargs)

    @pytest.mark.anyio
    async def test_logs_request_details(
        self,
        app_with_logging_middleware: FastAPI,
    ) -> None:
        """Log should include method, path, status_code, and duration."""
        with patch("redact_api.core.middleware.LOGGER") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app_with_logging_middleware),
                base_url="http://test",
            ) as client:
                await client.get("/test")

            call_kwargs = mock_logger.info.call_args
            extra = call_kwargs.kwargs.get("extra", {})

            assert extra.get("method") == "GET"
            assert extra.get("path") == "/test"
            assert extra.get("status_code") == HTTPStatus.OK
            assert "duration_seconds" in extra

    @pytest.mark.anyio
    async def test_logs_request_and_response_size(
        self,
        app_with_logging_middleware: FastAPI,
    ) -> None:
        """Log should include request and response size information."""
        with patch("redact_api.core.middleware.LOGGER") as mock_logger:
            async with AsyncClient(
                transport=ASGITransport(app=app_with_logging_middleware),
                base_url="http://test",
            ) as client:
                await client.get("/test")

            call_kwargs = mock_logger.info.call_args
            extra = call_kwargs.kwargs.get("extra", {})

            assert "request_size_bytes" in extra
            assert "response_size_bytes" in extra
