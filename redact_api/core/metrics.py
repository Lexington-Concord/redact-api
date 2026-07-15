"""Prometheus ASGI app for /metrics with custom business metrics.

OpenTelemetry Auto-Instrumentation:
    When using OpenTelemetry auto-instrumentation (recommended), the following
    HTTP metrics are automatically collected WITHOUT any code changes:

    - http.server.request.duration - Request latency histogram
    - http.server.active_requests - Active requests gauge
    - http.server.request.size - Request body size histogram
    - http.server.response.size - Response body size histogram

    Metrics include labels: http.method, http.route, http.status_code, etc.

    To enable OpenTelemetry auto-instrumentation:
        pip install opentelemetry-distro opentelemetry-exporter-prometheus
        opentelemetry-instrument python -m uvicorn app.main:app

Business Domain Metrics:
    This module defines CUSTOM metrics for application-specific operations that
    are not covered by auto-instrumentation. These track business logic events,
    domain operations, and application-specific performance indicators.

Usage Guidelines:
    - Record metrics AFTER successful operations (post-commit, post-response)
    - Use consistent label names across metrics (environment, query_type, etc.)
    - Keep histogram observations lightweight (avoid expensive operations inside timing)
    - Don't add metrics to every operation (performance overhead)
    - Focus on domain-specific operations (create, delete, upload, etc.)

Usage Examples:

    # Counter: Increment after successful operation
    from redact_api.core.metrics import users_created_total
    from redact_api.core.config import settings

    async def create_user(...):
        user = User(...)
        await session.commit()
        # Increment AFTER successful commit
        users_created_total.labels(environment=settings.environment).inc()
        return user

    # Histogram: Observe document upload sizes
    from redact_api.core.metrics import document_upload_size_bytes

    async def upload_document(file: UploadFile):
        file_data = await file.read()
        size_bytes = len(file_data)
        # Record size in histogram (no labels needed)
        document_upload_size_bytes.observe(size_bytes)
        ...

    # Histogram: Track database query duration
    from redact_api.core.metrics import database_query_duration_seconds
    import time

    start = time.perf_counter()
    result = await session.execute(query)
    duration = time.perf_counter() - start
    # Observe duration with query_type label
    database_query_duration_seconds.labels(query_type="select").observe(duration)

    # Gauge: Track active resource counts
    from redact_api.core.metrics import active_memberships_gauge

    # Increment when creating membership
    active_memberships_gauge.labels(environment=settings.environment).inc()

    # Decrement when deleting membership
    active_memberships_gauge.labels(environment=settings.environment).dec()

    # Counter with multiple labels
    from redact_api.core.metrics import activity_log_entries_created

    activity_log_entries_created.labels(
        resource_type="organization",
        action="delete"
    ).inc()

Viewing Metrics:
    Metrics are exposed at GET /metrics in Prometheus exposition format.

    Example output:
        # HELP users_created_total Total number of users created
        # TYPE users_created_total counter
        users_created_total{environment="production"} 1234.0
        users_created_total{environment="staging"} 56.0

        # HELP database_query_duration_seconds Database query duration in seconds
        # TYPE database_query_duration_seconds histogram
        database_query_duration_seconds_bucket{query_type="select",le="0.001"} 123
        database_query_duration_seconds_bucket{query_type="select",le="0.01"} 456
        database_query_duration_seconds_sum{query_type="select"} 12.34
        database_query_duration_seconds_count{query_type="select"} 500
"""

from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

# Business domain metrics (HTTP metrics come from OpenTelemetry auto-instrumentor)
users_created_total = Counter(
    "users_created_total",
    "Total number of users created",
    ["environment"],
)

organizations_created_total = Counter(
    "organizations_created_total",
    "Total number of organizations created",
    ["environment"],
)

memberships_created_total = Counter(
    "memberships_created_total",
    "Total number of memberships created",
    ["environment"],
)

documents_ingested_total = Counter(
    "documents_ingested_total",
    "Total number of documents successfully ingested",
    ["environment"],
)

active_memberships_gauge = Gauge(
    "active_memberships_gauge",
    "Current number of active memberships",
    ["environment"],
)

document_upload_size_bytes = Histogram(
    "document_upload_size_bytes",
    "Document upload file sizes in bytes",
    buckets=[1e5, 1e6, 10e6, 50e6, 100e6, 500e6],
)

database_query_duration_seconds = Histogram(
    "database_query_duration_seconds",
    "Database query duration in seconds",
    ["query_type"],
    buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1.0],
)

activity_log_entries_created = Counter(
    "activity_log_entries_created",
    "Total number of activity log entries created",
    ["resource_type", "action"],
)

# TaskIQ pipeline metrics (redact-api#8). Label shapes copy the worker template's
# metrics_mw contract: lifecycle counters carry (environment, task_name); the
# duration histogram and in-progress gauge carry task_name only.
tasks_started_total = Counter(
    "tasks_started_total",
    "Total number of tasks started",
    ["environment", "task_name"],
)

tasks_completed_total = Counter(
    "tasks_completed_total",
    "Total number of tasks completed successfully",
    ["environment", "task_name"],
)

tasks_failed_total = Counter(
    "tasks_failed_total",
    "Total number of tasks that failed",
    ["environment", "task_name"],
)

task_duration_seconds = Histogram(
    "task_duration_seconds",
    "Task execution duration in seconds",
    ["task_name"],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0, 3600.0],
)

tasks_in_progress = Gauge(
    "tasks_in_progress",
    "Number of tasks currently being executed",
    ["task_name"],
)

metrics_app = make_asgi_app()
