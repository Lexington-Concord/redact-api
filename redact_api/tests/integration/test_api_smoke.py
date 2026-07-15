"""Smoke tests for API integration.

These tests verify basic API functionality against a real database.
Run with: uv run pytest redact_api/tests/integration/test_api_smoke.py -v
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_integration(client: AsyncClient) -> None:
    """Verify health endpoint returns healthy status with real database.

    ``/health`` (readiness) also checks task-broker connectivity (redact-api#8); no
    RabbitMQ is available in this test environment, so that check is stubbed here the
    same way ``test_health.py`` does, keeping this smoke test focused on the real-database
    behavior it's named for.
    """
    with patch("redact_api.api.health._check_broker", new_callable=AsyncMock):
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_ping_endpoint_integration(client: AsyncClient) -> None:
    """Verify ping endpoint works."""
    response = await client.get("/ping")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "pong"
