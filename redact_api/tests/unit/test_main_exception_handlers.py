"""Tests for main.py exception handlers and lifespan events.

Tests the global exception handlers that provide consistent
error responses across the API.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from redact_api.core.config import ConfigurationError
from redact_api.main import (
    generic_exception_handler,
    lifespan,
    pydantic_validation_exception_handler,
    validation_exception_handler,
    value_error_exception_handler,
)

if TYPE_CHECKING:
    pass


class TestValidationExceptionHandler:
    """Tests for RequestValidationError handler."""

    @pytest.mark.asyncio
    async def test_returns_422_with_details(self) -> None:
        """Should return 422 with validation error details."""
        mock_request = MagicMock()
        exc = RequestValidationError(
            errors=[
                {
                    "loc": ["body", "email"],
                    "msg": "value is not a valid email address",
                    "type": "value_error.email",
                }
            ]
        )

        response = await validation_exception_handler(mock_request, exc)

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        body = bytes(response.body).decode()
        assert "VALIDATION_ERROR" in body
        assert "Request validation failed" in body


class TestPydanticValidationExceptionHandler:
    """Tests for Pydantic ValidationError handler."""

    @pytest.mark.asyncio
    async def test_returns_422_with_details(self) -> None:
        """Should return 422 with validation error details."""
        mock_request = MagicMock()

        # Create a proper validation error
        error = InitErrorDetails(
            type=PydanticCustomError("value_error", "Invalid value"),
            loc=("field",),
            input="bad_value",
        )
        exc = ValidationError.from_exception_data("TestModel", [error])

        response = await pydantic_validation_exception_handler(mock_request, exc)

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        body = bytes(response.body).decode()
        assert "VALIDATION_ERROR" in body
        assert "Data validation failed" in body


class TestValueErrorExceptionHandler:
    """Tests for ValueError handler."""

    @pytest.mark.asyncio
    async def test_returns_400_with_message(self) -> None:
        """Should return 400 with error message."""
        mock_request = MagicMock()
        exc = ValueError("Invalid UUID format")

        response = await value_error_exception_handler(mock_request, exc)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        body = bytes(response.body).decode()
        assert "INVALID_VALUE" in body
        assert "Invalid UUID format" in body

    @pytest.mark.asyncio
    async def test_returns_400_with_default_message_for_empty_error(self) -> None:
        """Should return default message for empty ValueError."""
        mock_request = MagicMock()
        exc = ValueError("")

        response = await value_error_exception_handler(mock_request, exc)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        body = bytes(response.body).decode()
        assert "Invalid value provided" in body


class TestGenericExceptionHandler:
    """Tests for generic Exception handler."""

    @pytest.mark.asyncio
    async def test_returns_500_with_sanitized_message(self) -> None:
        """Should return 500 with sanitized error message."""
        mock_request = MagicMock()
        exc = Exception("Internal database connection failed with password=secret123")

        response = await generic_exception_handler(mock_request, exc)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        body = bytes(response.body).decode()
        assert "INTERNAL_ERROR" in body
        assert "An internal server error occurred" in body
        # Should NOT expose internal details
        assert "secret123" not in body
        assert "database" not in body


class TestLifespanEvents:
    """Tests for application lifespan startup/shutdown."""

    @pytest.mark.asyncio
    async def test_lifespan_startup_validates_config(self) -> None:
        """Should validate configuration on startup."""
        mock_app = MagicMock()
        mock_app.state = MagicMock()

        mock_engine = AsyncMock()
        mock_engine.begin = MagicMock()

        # Create a proper async context manager for begin()
        mock_connection = AsyncMock()
        mock_connection.execute = AsyncMock()

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        mock_engine.begin.return_value = mock_context
        mock_engine.dispose = AsyncMock()

        with (
            patch("redact_api.main.settings") as mock_settings,
            patch("redact_api.main.create_db_engine", return_value=mock_engine),
            patch("redact_api.main.create_session_maker"),
        ):
            mock_settings.validate_config.return_value = ["Warning 1", "Warning 2"]
            mock_settings.db_pool_size = 5
            mock_settings.db_max_overflow = 10
            mock_settings.db_pool_timeout = 30
            mock_settings.db_pool_recycle = 1800
            mock_settings.db_pool_pre_ping = True
            mock_settings.database_url = "postgresql://user:pass@host/db"
            mock_settings.sqlalchemy_echo = False

            async with lifespan(mock_app):
                pass

            mock_settings.validate_config.assert_called_once()
            mock_engine.dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_startup_raises_on_config_error(self) -> None:
        """Should raise ConfigurationError on invalid config."""
        mock_app = MagicMock()

        with patch("redact_api.main.settings") as mock_settings:
            mock_settings.validate_config.side_effect = ConfigurationError("Invalid")

            with pytest.raises(ConfigurationError):
                async with lifespan(mock_app):
                    pass

    @pytest.mark.asyncio
    async def test_lifespan_startup_raises_on_db_connection_failure(self) -> None:
        """Should raise RuntimeError on database connection failure."""
        mock_app = MagicMock()
        mock_app.state = MagicMock()

        mock_engine = AsyncMock()

        # Make begin() raise an exception
        mock_engine.begin.side_effect = Exception("Connection refused")
        mock_engine.dispose = AsyncMock()

        with (
            patch("redact_api.main.settings") as mock_settings,
            patch("redact_api.main.create_db_engine", return_value=mock_engine),
            patch("redact_api.main.create_session_maker"),
        ):
            mock_settings.validate_config.return_value = []
            mock_settings.db_pool_size = 5
            mock_settings.db_max_overflow = 10
            mock_settings.db_pool_timeout = 30
            mock_settings.db_pool_recycle = 1800
            mock_settings.db_pool_pre_ping = True
            mock_settings.database_url = "postgresql://user:pass@host/db"
            mock_settings.sqlalchemy_echo = False

            with pytest.raises(RuntimeError, match="Failed to connect to database"):
                async with lifespan(mock_app):
                    pass
