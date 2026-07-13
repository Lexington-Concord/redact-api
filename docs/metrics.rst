Metrics and Observability
=========================

This guide explains how to use Prometheus metrics in the application for monitoring,
alerting, and observability.

Overview
--------

The application exposes metrics at ``GET /metrics`` in Prometheus exposition format.
Metrics are divided into two categories:

1. **HTTP Metrics** - Automatically collected by OpenTelemetry auto-instrumentation
2. **Business Domain Metrics** - Custom metrics tracking application-specific operations

Viewing Metrics
---------------

Metrics Endpoint
~~~~~~~~~~~~~~~~

Access metrics locally:

.. code-block:: bash

   curl http://localhost:8000/metrics

Example output:

.. code-block:: text

   # HELP users_created_total Total number of users created
   # TYPE users_created_total counter
   users_created_total{environment="production"} 1234.0

   # HELP database_query_duration_seconds Database query duration in seconds
   # TYPE database_query_duration_seconds histogram
   database_query_duration_seconds_bucket{query_type="select",le="0.001"} 123
   database_query_duration_seconds_bucket{query_type="select",le="0.01"} 456
   database_query_duration_seconds_sum{query_type="select"} 12.34
   database_query_duration_seconds_count{query_type="select"} 500

Available Metrics
-----------------

Business Domain Metrics
~~~~~~~~~~~~~~~~~~~~~~~~

These custom metrics track application-specific operations:

Counters
^^^^^^^^

**users_created_total**
   Total number of users created

   - Labels: ``environment`` (production, staging, local)
   - Location: ``services/user_service.py``
   - Recorded: After successful user creation

**organizations_created_total**
   Total number of organizations created

   - Labels: ``environment``
   - Location: ``services/organization_service.py``
   - Recorded: After successful organization creation

**memberships_created_total**
   Total number of memberships created

   - Labels: ``environment``
   - Location: ``services/membership_service.py``
   - Recorded: After successful membership creation

**activity_log_entries_created**
   Total number of activity log entries created

   - Labels: ``resource_type`` (user, organization, document), ``action`` (create, read, update, delete)
   - Location: ``core/activity_logging.py``
   - Recorded: By activity logging decorator

Gauges
^^^^^^

**active_memberships_gauge**
   Current number of active memberships

   - Labels: ``environment``
   - Location: ``services/membership_service.py``
   - Updated: Incremented on membership creation, decremented on deletion

Histograms
^^^^^^^^^^

**database_query_duration_seconds**
   Database query duration in seconds

   - Labels: ``query_type`` (select, insert, update, delete)
   - Buckets: [0.001, 0.01, 0.05, 0.1, 0.5, 1.0]
   - Location: ``services/user_service.py``, ``services/organization_service.py``, ``api/documents.py``
   - Recorded: On every database query operation

**document_upload_size_bytes**
   Document upload file sizes in bytes

   - Labels: None
   - Buckets: [100KB, 1MB, 10MB, 50MB, 100MB, 500MB]
   - Location: ``api/documents.py``
   - Recorded: On document upload after size validation

HTTP Metrics (OpenTelemetry)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When using OpenTelemetry auto-instrumentation, these metrics are collected automatically:

- ``http.server.request.duration`` - Request latency histogram
- ``http.server.active_requests`` - Active requests gauge
- ``http.server.request.size`` - Request body size histogram
- ``http.server.response.size`` - Response body size histogram

Labels include: ``http.method``, ``http.route``, ``http.status_code``, ``server.address``

To enable OpenTelemetry:

.. code-block:: bash

   pip install opentelemetry-distro opentelemetry-exporter-prometheus
   opentelemetry-instrument python -m uvicorn app.main:app

Adding New Metrics
------------------

When to Add Metrics
~~~~~~~~~~~~~~~~~~~

Add metrics for:

- **Domain operations**: User/organization creation, membership changes, document uploads
- **Performance tracking**: Database queries, external API calls, expensive computations
- **Resource tracking**: Active connections, queue lengths, cache sizes
- **Error tracking**: Failed operations, validation errors, rate limit hits

Do NOT add metrics for:

- Every single function call (performance overhead)
- Operations already tracked by OpenTelemetry (HTTP requests)
- High-cardinality labels (user IDs, email addresses, file names)

Step 1: Define Metric in core/metrics.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from prometheus_client import Counter, Gauge, Histogram

   # Counter example
   api_calls_total = Counter(
       "api_calls_total",
       "Total number of external API calls",
       ["service", "environment"],
   )

   # Gauge example
   cache_size_bytes = Gauge(
       "cache_size_bytes",
       "Current cache size in bytes",
       ["cache_name"],
   )

   # Histogram example
   api_response_time_seconds = Histogram(
       "api_response_time_seconds",
       "External API response time in seconds",
       ["service"],
       buckets=[0.1, 0.5, 1.0, 2.0, 5.0],
   )

Step 2: Import and Use Metric
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import time
   from myapp.core.metrics import api_calls_total, api_response_time_seconds
   from myapp.core.config import settings

   async def call_external_api(service: str):
       start = time.perf_counter()

       try:
           response = await http_client.get(f"https://{service}.example.com")
           duration = time.perf_counter() - start

           # Record metrics AFTER successful operation
           api_calls_total.labels(service=service, environment=settings.environment).inc()
           api_response_time_seconds.labels(service=service).observe(duration)

           return response
       except Exception as e:
           # Optionally track errors separately
           api_calls_total.labels(service=service, environment=settings.environment).inc()
           raise

Step 3: Document the Metric
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add to this documentation file:

- Metric name and description
- Labels and their possible values
- Where it's recorded (file location)
- When it's recorded (after commit, on error, etc.)
- Example usage and queries

Best Practices
--------------

Metric Recording
~~~~~~~~~~~~~~~~

1. **Record after success**: Only increment counters after successful operations to maintain accuracy

   .. code-block:: python

      await session.commit()  # May raise exception
      users_created_total.labels(environment=settings.environment).inc()  # Only if commit succeeds

2. **Use consistent labels**: Use the same label names across metrics (``environment``, not ``env``)

3. **Keep observations lightweight**: Avoid expensive operations inside timing blocks

   .. code-block:: python

      # Good - minimal overhead
      start = time.perf_counter()
      result = await db.execute(query)
      duration = time.perf_counter() - start
      database_query_duration_seconds.labels(query_type="select").observe(duration)

      # Bad - expensive operation in timing block
      start = time.perf_counter()
      result = await db.execute(query)
      processed = [complex_transform(r) for r in result]  # Don't time this
      duration = time.perf_counter() - start

4. **Avoid high-cardinality labels**: Never use labels with unbounded values

   .. code-block:: python

      # Good - bounded label values
      users_created_total.labels(environment=settings.environment).inc()

      # Bad - unbounded label values (will create millions of time series)
      users_created_total.labels(email=user.email).inc()  # DON'T DO THIS

Label Usage
~~~~~~~~~~~

Common label names:

- ``environment``: production, staging, local
- ``query_type``: select, insert, update, delete
- ``resource_type``: user, organization, document
- ``action``: create, read, update, delete
- ``status``: success, failure, timeout

Prometheus Integration
----------------------

Scrape Configuration
~~~~~~~~~~~~~~~~~~~~

Configure Prometheus to scrape the metrics endpoint:

.. code-block:: yaml

   # prometheus.yml
   scrape_configs:
     - job_name: 'fastapi-app'
       scrape_interval: 15s
       static_configs:
         - targets: ['app:8000']
       metrics_path: '/metrics'

Example Queries
~~~~~~~~~~~~~~~

**Request rate (from OpenTelemetry)**:

.. code-block:: promql

   rate(http_server_request_duration_count[5m])

**95th percentile request latency**:

.. code-block:: promql

   histogram_quantile(0.95, rate(http_server_request_duration_bucket[5m]))

**User creation rate**:

.. code-block:: promql

   rate(users_created_total[5m])

**Average database query duration**:

.. code-block:: promql

   rate(database_query_duration_seconds_sum[5m]) /
   rate(database_query_duration_seconds_count[5m])

**Active memberships by environment**:

.. code-block:: promql

   active_memberships_gauge{environment="production"}

**Document upload size 99th percentile**:

.. code-block:: promql

   histogram_quantile(0.99, rate(document_upload_size_bytes_bucket[5m]))

Alerting Rules
~~~~~~~~~~~~~~

Example Prometheus alerting rules:

.. code-block:: yaml

   # alerts.yml
   groups:
     - name: application
       rules:
         - alert: HighErrorRate
           expr: rate(http_server_request_duration_count{status_code=~"5.."}[5m]) > 0.05
           for: 5m
           annotations:
             summary: "High error rate detected"

         - alert: SlowDatabaseQueries
           expr: histogram_quantile(0.95, rate(database_query_duration_seconds_bucket[5m])) > 1.0
           for: 10m
           annotations:
             summary: "95th percentile database query duration > 1s"

         - alert: LargeDocumentUploads
           expr: histogram_quantile(0.95, rate(document_upload_size_bytes_bucket[5m])) > 100000000
           for: 5m
           annotations:
             summary: "95th percentile document upload size > 100MB"

Grafana Dashboards
------------------

Dashboard Setup
~~~~~~~~~~~~~~~

1. **Add Prometheus data source** in Grafana:

   - URL: ``http://prometheus:9090``
   - Access: Server (default)

2. **Create dashboard** with panels:

HTTP Metrics Panel
~~~~~~~~~~~~~~~~~~

**Request Rate**:

.. code-block:: promql

   sum(rate(http_server_request_duration_count[5m])) by (http_route)

**Error Rate**:

.. code-block:: promql

   sum(rate(http_server_request_duration_count{status_code=~"5.."}[5m])) by (http_route)

**95th Percentile Latency**:

.. code-block:: promql

   histogram_quantile(0.95,
     sum(rate(http_server_request_duration_bucket[5m])) by (le, http_route)
   )

Business Metrics Panel
~~~~~~~~~~~~~~~~~~~~~~

**User Growth**:

.. code-block:: promql

   sum(users_created_total) by (environment)

**Membership Growth Rate**:

.. code-block:: promql

   rate(memberships_created_total[1h])

**Active Memberships**:

.. code-block:: promql

   active_memberships_gauge{environment="production"}

Database Performance Panel
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Query Rate by Type**:

.. code-block:: promql

   sum(rate(database_query_duration_seconds_count[5m])) by (query_type)

**Average Query Duration**:

.. code-block:: promql

   rate(database_query_duration_seconds_sum[5m]) /
   rate(database_query_duration_seconds_count[5m])

**Slow Queries (>100ms)**:

.. code-block:: promql

   sum(rate(database_query_duration_seconds_bucket{le="0.1"}[5m])) -
   sum(rate(database_query_duration_seconds_bucket{le="0.05"}[5m]))

Troubleshooting
---------------

Metrics Not Appearing
~~~~~~~~~~~~~~~~~~~~~

1. Check ``ENABLE_METRICS`` environment variable is ``true``
2. Verify ``/metrics`` endpoint is accessible: ``curl http://localhost:8000/metrics``
3. Check Prometheus scrape status: ``http://prometheus:9090/targets``
4. Ensure metric is being recorded (add logging around metric calls)

High Cardinality Issues
~~~~~~~~~~~~~~~~~~~~~~~

If Prometheus becomes slow or runs out of memory:

1. Identify high-cardinality metrics:

   .. code-block:: promql

      topk(10, count by (__name__, job)({__name__=~".+"}))

2. Review label usage - remove labels with unbounded values
3. Consider using metric relabeling in Prometheus to drop high-cardinality labels

Missing Labels
~~~~~~~~~~~~~~

If labels aren't showing up:

1. Verify label is defined in metric constructor:

   .. code-block:: python

      users_created_total = Counter(
          "users_created_total",
          "Total users created",
          ["environment"],  # Must declare labels here
      )

2. Ensure label is provided when recording:

   .. code-block:: python

      users_created_total.labels(environment=settings.environment).inc()

Further Reading
---------------

- `Prometheus Best Practices <https://prometheus.io/docs/practices/naming/>`_
- `OpenTelemetry Python <https://opentelemetry.io/docs/instrumentation/python/>`_
- `Prometheus Python Client <https://github.com/prometheus/client_python>`_
- `Grafana Dashboards <https://grafana.com/docs/grafana/latest/dashboards/>`_
