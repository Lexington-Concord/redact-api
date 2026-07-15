"""Tests for health check endpoints including error path coverage."""

from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DatabaseError, OperationalError


@pytest.mark.asyncio
async def test_ping(client: AsyncClient) -> None:
    """Ping endpoint returns pong message."""
    response = await client.get("/ping")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"message": "pong"}


@pytest.mark.asyncio
async def test_health_success(client: AsyncClient) -> None:
    """Readiness endpoint returns ok when the database and broker are both healthy."""
    with patch("redact_api.api.health._check_broker", new_callable=AsyncMock):
        response = await client.get("/health")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_live_success(client: AsyncClient) -> None:
    """Liveness endpoint returns ok on a healthy database and never checks the broker."""
    with patch("redact_api.api.health._check_broker", new_callable=AsyncMock) as mock_broker:
        response = await client.get("/health/live")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}
    mock_broker.assert_not_called()


@pytest.mark.asyncio
async def test_health_returns_503_on_broker_unavailable(client: AsyncClient) -> None:
    """Readiness endpoint returns 503 when the broker cannot be reached."""
    with patch("redact_api.api.health.aio_pika.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = ConnectionError("broker down")

        response = await client.get("/health")

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.json()["detail"] == "Broker unavailable"


class TestHealthErrorPaths:
    """Test error handling paths in health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_503_on_timeout(self, client: AsyncClient) -> None:
        """Health endpoint returns 503 when database times out."""
        with patch("redact_api.api.health.asyncio.wait_for") as mock_wait:
            mock_wait.side_effect = TimeoutError()

            response = await client.get("/health")

            assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
            assert response.json()["detail"] == "Database timeout"

    @pytest.mark.asyncio
    async def test_health_returns_503_on_operational_error(self, client: AsyncClient) -> None:
        """Health endpoint returns 503 when database connection fails."""
        with patch("redact_api.api.health.asyncio.wait_for") as mock_wait:
            mock_wait.side_effect = OperationalError(None, None, Exception("connection refused"))

            response = await client.get("/health")

            assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
            assert response.json()["detail"] == "Database unavailable"

    @pytest.mark.asyncio
    async def test_health_returns_503_on_database_error(self, client: AsyncClient) -> None:
        """Health endpoint returns 503 on generic database error."""
        with patch("redact_api.api.health.asyncio.wait_for") as mock_wait:
            mock_wait.side_effect = DatabaseError(None, None, Exception("query failed"))

            response = await client.get("/health")

            assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
            assert response.json()["detail"] == "Database error"


class TestHealthLogging:
    """Test logging behavior in health endpoint."""

    @pytest.mark.asyncio
    async def test_health_logs_success_with_timing(self, client: AsyncClient) -> None:
        """Health check logs success with response time."""
        with (
            patch("redact_api.api.health._check_broker", new_callable=AsyncMock),
            patch("redact_api.api.health.logger") as mock_logger,
        ):
            response = await client.get("/health")

            assert response.status_code == HTTPStatus.OK
            mock_logger.info.assert_called()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "health_check_success"
            assert "db_response_time_ms" in call_args[1]["extra"]

    @pytest.mark.asyncio
    async def test_health_logs_timeout_warning(self, client: AsyncClient) -> None:
        """Health check logs warning on timeout."""
        with patch("redact_api.api.health.asyncio.wait_for") as mock_wait:
            mock_wait.side_effect = TimeoutError()

            with patch("redact_api.api.health.logger") as mock_logger:
                response = await client.get("/health")

                assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
                mock_logger.warning.assert_called()
                call_args = mock_logger.warning.call_args
                assert call_args[0][0] == "health_check_timeout"
