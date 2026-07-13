"""Tests for HTTP client utilities.

Tests cover the async context manager for cross-service HTTP communication,
including timeout configuration, headers, and proper resource cleanup.
"""

import httpx
import pytest

from redact_api.core.http_client import http_client


class TestHttpClient:
    """Tests for http_client async context manager."""

    @pytest.mark.asyncio
    async def test_yields_async_client(self) -> None:
        """Context manager yields an httpx.AsyncClient instance."""
        async with http_client() as client:
            assert isinstance(client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_default_timeout_is_30_seconds(self) -> None:
        """Default timeout configuration is 30 seconds."""
        async with http_client() as client:
            assert client.timeout.connect == 30.0
            assert client.timeout.read == 30.0
            assert client.timeout.write == 30.0
            assert client.timeout.pool == 30.0

    @pytest.mark.asyncio
    async def test_custom_timeout_5_seconds(self) -> None:
        """Custom timeout of 5 seconds is applied correctly."""
        async with http_client(timeout=5.0) as client:
            assert client.timeout.connect == 5.0
            assert client.timeout.read == 5.0
            assert client.timeout.write == 5.0
            assert client.timeout.pool == 5.0

    @pytest.mark.asyncio
    async def test_custom_timeout_10_seconds(self) -> None:
        """Custom timeout of 10 seconds is applied correctly."""
        async with http_client(timeout=10.0) as client:
            assert client.timeout.connect == 10.0
            assert client.timeout.read == 10.0

    @pytest.mark.asyncio
    async def test_custom_timeout_60_seconds(self) -> None:
        """Custom timeout of 60 seconds is applied correctly."""
        async with http_client(timeout=60.0) as client:
            assert client.timeout.connect == 60.0
            assert client.timeout.read == 60.0

    @pytest.mark.asyncio
    async def test_user_agent_header_is_set(self) -> None:
        """User-Agent header is set on the client."""
        async with http_client() as client:
            user_agent = client.headers.get("User-Agent")

            assert user_agent is not None
            assert user_agent.startswith("redact_api/")

    @pytest.mark.asyncio
    async def test_user_agent_includes_environment(self) -> None:
        """User-Agent header includes the environment from settings."""
        async with http_client() as client:
            user_agent = client.headers.get("User-Agent")

            # User-Agent format is "redact_api/{environment}"
            # Default environment is "local"
            assert user_agent is not None
            assert "redact_api/" in user_agent

    @pytest.mark.asyncio
    async def test_client_is_usable_within_context(self) -> None:
        """Client can be used to build requests within context."""
        async with http_client() as client:
            # Verify client can build a request (doesn't actually send)
            request = client.build_request("GET", "https://example.com/test")

            assert request.method == "GET"
            assert str(request.url) == "https://example.com/test"

    @pytest.mark.asyncio
    async def test_client_properly_closes_after_context_exit(self) -> None:
        """Client is closed after exiting the context manager."""
        client_ref: httpx.AsyncClient | None = None

        async with http_client() as client:
            client_ref = client
            assert not client.is_closed

        # After exiting context, client should be closed
        assert client_ref is not None
        assert client_ref.is_closed

    @pytest.mark.asyncio
    async def test_multiple_contexts_create_independent_clients(self) -> None:
        """Each context manager invocation creates an independent client."""
        async with http_client(timeout=5.0) as client1, http_client(timeout=10.0) as client2:
            # Clients should have different timeouts
            assert client1.timeout.connect == 5.0
            assert client2.timeout.connect == 10.0

            # Clients should be different instances
            assert client1 is not client2

    @pytest.mark.asyncio
    async def test_client_closes_on_normal_exit(self) -> None:
        """Client is properly closed on normal context exit."""
        client_ref: httpx.AsyncClient | None = None

        async with http_client() as client:
            client_ref = client
            # Perform some operation
            _ = client.headers.get("User-Agent")

        # Client should be closed after normal exit
        assert client_ref is not None
        assert client_ref.is_closed
