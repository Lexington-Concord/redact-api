"""Tests for Prometheus metrics module.

These are unit tests that do not require database access.
"""

from typing import cast

import pytest

from redact_api.core.metrics import (
    active_memberships_gauge,
    activity_log_entries_created,
    database_query_duration_seconds,
    document_upload_size_bytes,
    memberships_created_total,
    metrics_app,
    organizations_created_total,
    users_created_total,
)


# Override autouse database fixtures from conftest.py for unit tests
@pytest.fixture
def reset_db() -> None:
    """No-op override for unit tests that don't need database."""


@pytest.fixture
def default_auth_user_in_org() -> None:
    """No-op override for unit tests that don't need database."""


class TestCounterMetrics:
    """Tests for counter metrics."""

    def test_users_created_total_increments(self) -> None:
        counter = users_created_total.labels(environment="test_users")
        before = counter._value.get()

        counter.inc()

        after = counter._value.get()
        assert after == before + 1

    def test_organizations_created_total_increments(self) -> None:
        counter = organizations_created_total.labels(environment="test_orgs")
        before = counter._value.get()

        counter.inc()

        after = counter._value.get()
        assert after == before + 1

    def test_memberships_created_total_increments(self) -> None:
        counter = memberships_created_total.labels(environment="test_memberships")
        before = counter._value.get()

        counter.inc()

        after = counter._value.get()
        assert after == before + 1

    def test_activity_log_entries_created_with_labels(self) -> None:
        counter = activity_log_entries_created.labels(resource_type="user", action="create")
        before = counter._value.get()

        counter.inc()

        after = counter._value.get()
        assert after == before + 1

    def test_activity_log_entries_created_different_labels(self) -> None:
        counter_create = activity_log_entries_created.labels(resource_type="organization", action="create")
        counter_delete = activity_log_entries_created.labels(resource_type="organization", action="delete")
        before_create = counter_create._value.get()
        before_delete = counter_delete._value.get()

        counter_create.inc()

        # Only the create counter should increment
        assert counter_create._value.get() == before_create + 1
        assert counter_delete._value.get() == before_delete

    def test_counter_inc_by_value(self) -> None:
        counter = users_created_total.labels(environment="test_inc_value")
        before = counter._value.get()

        counter.inc(5)

        after = counter._value.get()
        assert after == before + 5


class TestGaugeMetrics:
    """Tests for gauge metrics."""

    def test_active_memberships_gauge_inc_and_dec(self) -> None:
        gauge = active_memberships_gauge.labels(environment="test_gauge")
        initial = gauge._value.get()

        gauge.inc()
        assert gauge._value.get() == initial + 1

        gauge.dec()
        assert gauge._value.get() == initial

    def test_active_memberships_gauge_set(self) -> None:
        gauge = active_memberships_gauge.labels(environment="test_gauge_set")

        gauge.set(42)

        assert gauge._value.get() == 42

    def test_active_memberships_gauge_inc_by_value(self) -> None:
        gauge = active_memberships_gauge.labels(environment="test_gauge_inc")
        gauge.set(0)

        gauge.inc(10)

        assert gauge._value.get() == 10

    def test_active_memberships_gauge_dec_by_value(self) -> None:
        gauge = active_memberships_gauge.labels(environment="test_gauge_dec")
        gauge.set(20)

        gauge.dec(5)

        assert gauge._value.get() == 15


class TestHistogramMetrics:
    """Tests for histogram metrics."""

    def test_document_upload_size_bytes_observe(self) -> None:
        one_mb = 1024 * 1024

        # Should not raise an error
        document_upload_size_bytes.observe(one_mb)

    def test_document_upload_size_bytes_observe_various_sizes(self) -> None:
        sizes = [
            100_000,  # 100KB - below first bucket
            1_000_000,  # 1MB
            10_000_000,  # 10MB
            50_000_000,  # 50MB
        ]

        # Should not raise errors for any size
        for size in sizes:
            document_upload_size_bytes.observe(size)

    def test_database_query_duration_seconds_observe(self) -> None:
        duration = 0.05  # 50ms

        # Should not raise an error
        database_query_duration_seconds.labels(query_type="select").observe(duration)

    def test_database_query_duration_seconds_different_query_types(self) -> None:
        # Should not raise errors for different query types
        database_query_duration_seconds.labels(query_type="select").observe(0.01)
        database_query_duration_seconds.labels(query_type="insert").observe(0.02)
        database_query_duration_seconds.labels(query_type="update").observe(0.03)
        database_query_duration_seconds.labels(query_type="delete").observe(0.04)

    def test_database_query_duration_various_durations(self) -> None:
        histogram = database_query_duration_seconds.labels(query_type="test_durations")
        durations = [
            0.0005,  # 0.5ms - below first bucket
            0.001,  # 1ms
            0.01,  # 10ms
            0.05,  # 50ms
            0.1,  # 100ms
            0.5,  # 500ms
            1.0,  # 1s
        ]

        # Should not raise errors for any duration
        for duration in durations:
            histogram.observe(duration)


class TestMetricsApp:
    """Tests for the ASGI metrics app."""

    def test_metrics_app_is_not_none(self) -> None:
        assert metrics_app is not None

    def test_metrics_app_is_callable(self) -> None:
        assert callable(metrics_app)

    @pytest.mark.anyio
    async def test_metrics_app_responds_to_request(self) -> None:
        """Test that metrics_app can handle an ASGI request."""
        received_status: int | None = None
        received_headers: list[tuple[bytes, bytes]] = []
        body_parts: list[bytes] = []

        async def receive() -> dict[str, str | bytes]:
            return {"type": "http.request", "body": b""}

        async def send(message: dict[str, object]) -> None:
            nonlocal received_status, received_headers, body_parts
            if message["type"] == "http.response.start":
                received_status = cast(int, message.get("status"))
                received_headers = list(cast(list[tuple[bytes, bytes]], message.get("headers", [])))
            elif message["type"] == "http.response.body":
                body = cast(bytes, message.get("body", b""))
                if body:
                    body_parts.append(body)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/metrics",
            "query_string": b"",
            "headers": [],
        }

        await metrics_app(scope, receive, send)

        assert received_status == 200
        body = b"".join(body_parts).decode("utf-8")
        # Should contain prometheus metrics format
        assert "# HELP" in body or "# TYPE" in body or "users_created_total" in body


class TestMetricLabels:
    """Tests for metric label behavior."""

    def test_counter_creates_separate_time_series_per_label(self) -> None:
        env1 = users_created_total.labels(environment="production")
        env2 = users_created_total.labels(environment="staging")

        before1 = env1._value.get()
        before2 = env2._value.get()

        env1.inc()

        # Only production should increment
        assert env1._value.get() == before1 + 1
        assert env2._value.get() == before2

    def test_gauge_creates_separate_time_series_per_label(self) -> None:
        gauge1 = active_memberships_gauge.labels(environment="test_label_1")
        gauge2 = active_memberships_gauge.labels(environment="test_label_2")

        gauge1.set(100)
        gauge2.set(200)

        assert gauge1._value.get() == 100
        assert gauge2._value.get() == 200
