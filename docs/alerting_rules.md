# Alerting Rules

Prometheus alerting rules for redact_api. Import these into your Prometheus AlertManager configuration.

## Quick Start

1. Copy the alert rules below to your Prometheus rules file
2. Configure AlertManager notification channels (Slack, PagerDuty, Email)
3. Test alerts using the verification commands at the bottom

---

## Alert Configuration

### prometheus-rules.yaml

```yaml
groups:
  - name: redact_api_availability
    rules:
      # High Error Rate - Critical
      - alert: HighErrorRate
        expr: |
          (
            sum(rate(http_requests_total{status=~"5.."}[5m]))
            /
            sum(rate(http_requests_total[5m]))
          ) > 0.05
        for: 2m
        labels:
          severity: critical
          service: redact_api
        annotations:
          summary: "High error rate detected (> 5%)"
          description: "Error rate is {{ $value | humanizePercentage }} over the last 5 minutes."
          runbook_url: "https://wiki.example.com/runbooks/redact_api/high-error-rate"

      # Service Down
      - alert: ServiceDown
        expr: up{job="redact_api"} == 0
        for: 1m
        labels:
          severity: critical
          service: redact_api
        annotations:
          summary: "redact_api service is down"
          description: "The redact_api service has been unreachable for more than 1 minute."
          runbook_url: "https://wiki.example.com/runbooks/redact_api/service-down"

      # Health Check Failing
      - alert: HealthCheckFailing
        expr: |
          probe_success{job="redact_api-health"} == 0
        for: 2m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "Health check failing"
          description: "The /health endpoint is not returning success."

  - name: redact_api_latency
    rules:
      # Slow Response Time (P95)
      - alert: SlowResponseTimeP95
        expr: |
          histogram_quantile(0.95,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
          ) > 1.0
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "95th percentile latency above 1 second"
          description: "P95 latency is {{ $value | humanizeDuration }}."
          runbook_url: "https://wiki.example.com/runbooks/redact_api/slow-response"

      # Very Slow Response Time (P99)
      - alert: SlowResponseTimeP99
        expr: |
          histogram_quantile(0.99,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
          ) > 3.0
        for: 5m
        labels:
          severity: critical
          service: redact_api
        annotations:
          summary: "99th percentile latency above 3 seconds"
          description: "P99 latency is {{ $value | humanizeDuration }}. Investigate immediately."

      # Endpoint-Specific Slow Response
      - alert: EndpointSlowResponse
        expr: |
          histogram_quantile(0.95,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (le, handler)
          ) > 2.0
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "Endpoint {{ $labels.handler }} is slow"
          description: "P95 latency for {{ $labels.handler }} is {{ $value | humanizeDuration }}."

  - name: redact_api_database
    rules:
      # Database Connection Failures
      - alert: DatabaseConnectionFailures
        expr: |
          rate(db_connection_errors_total[5m]) > 0
        for: 2m
        labels:
          severity: critical
          service: redact_api
        annotations:
          summary: "Database connection errors detected"
          description: "{{ $value }} connection errors per second in the last 5 minutes."
          runbook_url: "https://wiki.example.com/runbooks/redact_api/db-connection-failure"

      # Connection Pool Exhausted
      - alert: ConnectionPoolExhausted
        expr: |
          (db_connection_pool_size - db_connection_pool_available)
          / db_connection_pool_size > 0.9
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "Database connection pool nearly exhausted"
          description: "Connection pool is {{ $value | humanizePercentage }} utilized."

      # Slow Database Queries
      - alert: SlowDatabaseQueries
        expr: |
          histogram_quantile(0.95,
            sum(rate(db_query_duration_seconds_bucket[5m])) by (le)
          ) > 0.5
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "Database queries are slow"
          description: "P95 query time is {{ $value | humanizeDuration }}."

  - name: redact_api_authentication
    rules:
      # High Authentication Failure Rate
      - alert: HighAuthFailureRate
        expr: |
          (
            sum(rate(http_requests_total{status="401"}[5m]))
            /
            sum(rate(http_requests_total[5m]))
          ) > 0.1
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "High authentication failure rate (> 10%)"
          description: "{{ $value | humanizePercentage }} of requests are failing authentication."

      # JWT Validation Errors
      - alert: JWTValidationErrors
        expr: |
          rate(jwt_validation_errors_total[5m]) > 1
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "JWT validation errors increasing"
          description: "{{ $value }} JWT validation errors per second."

      # JWKS Fetch Failures
      - alert: JWKSFetchFailures
        expr: |
          rate(jwks_fetch_errors_total[5m]) > 0
        for: 2m
        labels:
          severity: critical
          service: redact_api
        annotations:
          summary: "JWKS fetch failing"
          description: "Cannot fetch JWKS from auth provider. Authentication may fail."

  - name: redact_api_rate_limiting
    rules:
      # Rate Limit Hit
      - alert: RateLimitExceeded
        expr: |
          rate(http_requests_total{status="429"}[5m]) > 10
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "High rate of rate-limited requests"
          description: "{{ $value }} requests per second are being rate limited."

  - name: redact_api_storage
    rules:
      # Storage Operation Failures
      - alert: StorageOperationFailures
        expr: |
          rate(storage_operation_errors_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "Storage operations failing"
          description: "{{ $value }} storage errors per second."

      # Storage Retries
      - alert: HighStorageRetryRate
        expr: |
          rate(storage_operation_retries_total[5m]) > 1
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "High storage retry rate"
          description: "Storage operations are experiencing transient failures."

  - name: redact_api_resources
    rules:
      # High Memory Usage
      - alert: HighMemoryUsage
        expr: |
          (container_memory_usage_bytes{container="redact_api"}
           / container_spec_memory_limit_bytes{container="redact_api"}) > 0.9
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "High memory usage (> 90%)"
          description: "Memory usage is {{ $value | humanizePercentage }}."

      # High CPU Usage
      - alert: HighCPUUsage
        expr: |
          rate(container_cpu_usage_seconds_total{container="redact_api"}[5m])
          / container_spec_cpu_quota{container="redact_api"} > 0.9
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "High CPU usage (> 90%)"
          description: "CPU usage is {{ $value | humanizePercentage }}."

      # Pod Restart
      - alert: PodRestarting
        expr: |
          increase(kube_pod_container_status_restarts_total{container="redact_api"}[1h]) > 3
        for: 5m
        labels:
          severity: warning
          service: redact_api
        annotations:
          summary: "Pod restarting frequently"
          description: "{{ $value }} restarts in the last hour."
```

---

## AlertManager Configuration

### alertmanager.yaml

```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'severity', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default'
  routes:
    # Critical alerts go to PagerDuty
    - match:
        severity: critical
      receiver: 'pagerduty-critical'
      continue: true

    # All alerts also go to Slack
    - match:
        service: redact_api
      receiver: 'slack-redact_api'

receivers:
  - name: 'default'
    # Fallback receiver

  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: '<YOUR_PAGERDUTY_SERVICE_KEY>'
        severity: critical

  - name: 'slack-redact_api'
    slack_configs:
      - api_url: '<YOUR_SLACK_WEBHOOK_URL>'
        channel: '#redact_api-alerts'
        title: '{{ .Status | toUpper }}: {{ .CommonAnnotations.summary }}'
        text: '{{ .CommonAnnotations.description }}'
        send_resolved: true

inhibit_rules:
  # Don't alert on warnings if there's a critical
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'service']
```

---

## Severity Levels

| Severity | Response Time | Examples |
|----------|---------------|----------|
| **critical** | Immediate (page on-call) | Service down, database unreachable, >5% error rate |
| **warning** | Next business hour | Slow responses, high memory, rate limiting |
| **info** | Review in daily standup | Unusual patterns, non-urgent anomalies |

---

## Alert Tuning

### Reducing Alert Noise

If an alert is too noisy:

1. **Increase `for` duration**: Require the condition to persist longer
2. **Adjust threshold**: Make the trigger less sensitive
3. **Add inhibition rules**: Suppress related alerts

### Alert Review Checklist

Weekly review:
- [ ] Any alerts firing constantly? (tune thresholds)
- [ ] Any critical incidents missed? (add new alerts)
- [ ] Alert fatigue reported? (consolidate/inhibit)

---

## Testing Alerts

### Manually Trigger Alerts

```bash
# Simulate high error rate
for i in {1..100}; do
  curl -s http://localhost:8000/nonexistent-endpoint || true
done

# Simulate slow response (if you have a slow endpoint for testing)
curl http://localhost:8000/api/v1/test/slow?delay=5

# Check Prometheus for pending alerts
curl http://localhost:9090/api/v1/alerts
```

### Verify AlertManager

```bash
# Check AlertManager status
curl http://localhost:9093/api/v1/status

# List active alerts
curl http://localhost:9093/api/v1/alerts

# Manually send test alert
curl -X POST http://localhost:9093/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '[{
    "labels": {
      "alertname": "TestAlert",
      "severity": "warning",
      "service": "redact_api"
    },
    "annotations": {
      "summary": "Test alert",
      "description": "This is a test alert"
    }
  }]'
```

---

## Custom Metrics

To add custom metrics for alerting, update your application code:

```python
from prometheus_client import Counter, Histogram

# Custom counter for business metrics
orders_created = Counter(
    'orders_created_total',
    'Total orders created',
    ['status']
)

# Custom histogram for specific operations
payment_processing_time = Histogram(
    'payment_processing_seconds',
    'Time spent processing payments',
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0]
)

# Usage in your code
orders_created.labels(status='success').inc()
with payment_processing_time.time():
    process_payment()
```

Then add alerts for these metrics:

```yaml
- alert: LowOrderCreationRate
  expr: rate(orders_created_total[1h]) < 10
  for: 30m
  labels:
    severity: warning
  annotations:
    summary: "Order creation rate is low"
```

---

## Runbook Links

Each alert should link to a runbook. Create runbooks for:

- [High Error Rate](https://wiki.example.com/runbooks/redact_api/high-error-rate)
- [Service Down](https://wiki.example.com/runbooks/redact_api/service-down)
- [Database Connection Failure](https://wiki.example.com/runbooks/redact_api/db-connection-failure)
- [Slow Response Time](https://wiki.example.com/runbooks/redact_api/slow-response)

---

**Last Updated**: 2026-01-15
**Maintainer**: redact_api team
