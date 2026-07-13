"""Smoke tests for API integration.

These tests verify basic API functionality against a real database.
Run with: uv run pytest redact_api/tests/integration/test_api_smoke.py -v
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_integration(client: AsyncClient) -> None:
    """Verify health endpoint returns healthy status with real database."""
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
