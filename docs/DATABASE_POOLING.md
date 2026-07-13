# Database Connection Pooling Guide

## Overview

SQLAlchemy connection pooling manages a pool of reusable database connections to minimize the overhead of creating new connections for each request. Proper pool sizing prevents connection exhaustion while avoiding resource waste.

## Pool Configuration Settings

The template exposes five pool configuration settings via environment variables:

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| `DB_POOL_SIZE` | 5 | 1-100 | Maximum number of connections to maintain in the pool |
| `DB_MAX_OVERFLOW` | 10 | 0-100 | Maximum connections to create beyond `pool_size` |
| `DB_POOL_TIMEOUT` | 30 | ≥1 | Seconds to wait before raising timeout error |
| `DB_POOL_RECYCLE` | 3600 | ≥-1 | Seconds before recycling connections (-1 disables) |
| `DB_POOL_PRE_PING` | true | bool | Test connection liveness before using |

**Total maximum connections**: `DB_POOL_SIZE + DB_MAX_OVERFLOW`

## Pool Sizing Formula

```
pool_size = (num_pods * concurrent_requests_per_pod) / expected_query_time_seconds
```

**Example calculation**:
- 3 pods
- 10 concurrent requests per pod
- Average query time: 0.1 seconds

```
pool_size = (3 * 10) / 0.1 = 300 connections total
pool_size per pod = 300 / 3 = 100 connections per pod
```

Set `DB_POOL_SIZE=80` and `DB_MAX_OVERFLOW=20` for headroom.

## Environment-Specific Recommendations

### Local Development
```bash
DB_POOL_SIZE=2
DB_MAX_OVERFLOW=3
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_POOL_PRE_PING=true
```

**Rationale**: Single developer, low concurrency, fast connection recycling for quick feedback.

### Staging
```bash
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_POOL_PRE_PING=true
```

**Rationale**: Mirrors production topology (multiple pods) but with lower traffic. Total max: 20 connections per pod.

### Production
```bash
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800  # 30 minutes
DB_POOL_PRE_PING=true
```

**Rationale**: Higher concurrency, shorter recycle time to avoid stale connections. Total max: 40 connections per pod.

**Critical**: Coordinate with PostgreSQL `max_connections` setting (see below).

## PostgreSQL max_connections Tuning

PostgreSQL limits total connections via `max_connections` (default: 100).

**Formula**:
```
postgres_max_connections >= (num_pods * (DB_POOL_SIZE + DB_MAX_OVERFLOW)) + reserved_connections
```

**Example**:
- 5 pods
- `DB_POOL_SIZE=20`, `DB_MAX_OVERFLOW=20`
- Reserved connections: 10 (for admin, monitoring, migrations)

```
postgres_max_connections >= (5 * 40) + 10 = 210
```

Set `max_connections=250` in `postgresql.conf` for headroom.

**AWS RDS**: Use parameter groups to set `max_connections`. Default scales with instance size.

**Note**: Each PostgreSQL connection consumes memory (~10MB). Monitor memory usage when increasing `max_connections`.

## Connection Leak Detection

### Symptoms
- `TimeoutError: QueuePool limit exceeded` errors
- Slow request response times
- Database connections remain in `idle in transaction` state

### Diagnostic Queries

**Check active connections per application**:
```sql
SELECT
  application_name,
  state,
  COUNT(*) as connection_count
FROM pg_stat_activity
WHERE datname = 'your_database_name'
GROUP BY application_name, state
ORDER BY connection_count DESC;
```

**Find long-running idle transactions** (potential leaks):
```sql
SELECT
  pid,
  usename,
  application_name,
  state,
  query,
  state_change,
  NOW() - state_change AS duration
FROM pg_stat_activity
WHERE
  state = 'idle in transaction'
  AND datname = 'your_database_name'
  AND NOW() - state_change > interval '5 minutes'
ORDER BY duration DESC;
```

### Common Causes and Fixes

**1. Missing session.close() in exception paths**
- **Fix**: Use `async with async_session_maker() as session:` pattern (template default)
- Sessions auto-close when context manager exits

**2. Long-running transactions holding connections**
- **Fix**: Break large operations into smaller transactions
- **Fix**: Use background tasks for long-running operations

**3. Pool exhaustion under load**
- **Fix**: Increase `DB_POOL_SIZE` and `DB_MAX_OVERFLOW`
- **Fix**: Add more pods to distribute load
- **Fix**: Optimize slow queries to reduce connection hold time

## Pool Exhaustion Troubleshooting

### Error Message
```
sqlalchemy.exc.TimeoutError: QueuePool limit of size X overflow Y reached,
connection timed out, timeout 30.00
```

### Immediate Actions

1. **Check current pool usage** (application metrics):
   ```python
   # Add to health check endpoint
   pool = engine.pool
   metrics = {
       "pool_size": pool.size(),
       "checked_in": pool.checkedin(),
       "checked_out": pool.checkedout(),
       "overflow": pool.overflow(),
   }
   ```

2. **Identify slow queries**:
   ```sql
   SELECT
     query,
     calls,
     total_exec_time,
     mean_exec_time,
     max_exec_time
   FROM pg_stat_statements
   ORDER BY mean_exec_time DESC
   LIMIT 10;
   ```
   (Requires `pg_stat_statements` extension)

3. **Kill idle transactions** (if safe):
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE
     state = 'idle in transaction'
     AND NOW() - state_change > interval '10 minutes';
   ```

### Long-Term Solutions

- **Horizontal scaling**: Add more pods to distribute connection load
- **Query optimization**: Add indexes, optimize N+1 queries, use connection-efficient patterns
- **Connection pooling proxy**: Use PgBouncer for transaction-level pooling
- **Read replicas**: Route read-only queries to replicas to reduce primary load

## Pre-Ping Behavior

`DB_POOL_PRE_PING=true` (default) tests connection liveness before use:

**How it works**:
1. Before returning connection from pool, SQLAlchemy runs `SELECT 1`
2. If connection is dead (network issue, database restart), it's discarded
3. New connection is created and returned

**Trade-offs**:
- **Pro**: Prevents "connection already closed" errors
- **Pro**: Automatic recovery from database restarts
- **Con**: Adds small latency overhead (~1-2ms per query)

**When to disable**:
- Ultra-low latency requirements (<5ms p99)
- Highly stable network and database (rare restarts)
- Application handles connection errors gracefully

**Recommendation**: Keep enabled unless profiling shows unacceptable overhead.

## Connection Recycle Strategy

`DB_POOL_RECYCLE=3600` (1 hour) prevents stale connections.

**Why recycle?**
- Database firewalls may close idle connections (Azure: 4 minutes, AWS RDS: variable)
- PostgreSQL may terminate long-lived connections during maintenance
- Prevents accumulation of connection-level state issues

**Tuning guidance**:
- **Cloud databases**: Set to 50% of cloud provider's idle timeout
  - Azure Database for PostgreSQL: `DB_POOL_RECYCLE=120` (2 minutes)
  - AWS RDS: `DB_POOL_RECYCLE=1800` (30 minutes)
- **Self-hosted**: `DB_POOL_RECYCLE=3600` (1 hour) is safe
- **Never disable** (`-1`) in production unless you control all network infrastructure

## Monitoring Pool Health

### Key Metrics

Track these metrics in production (via Prometheus or CloudWatch):

```python
# redact_api/core/metrics.py example
from prometheus_client import Gauge

db_pool_size = Gauge(
    "db_pool_size_total",
    "Total connection pool size",
)
db_pool_checked_in = Gauge(
    "db_pool_checked_in_connections",
    "Number of connections checked into the pool",
)
db_pool_checked_out = Gauge(
    "db_pool_checked_out_connections",
    "Number of connections checked out from the pool",
)
db_pool_overflow = Gauge(
    "db_pool_overflow_connections",
    "Number of overflow connections created",
)

def update_pool_metrics():
    pool = engine.pool
    db_pool_size.set(pool.size())
    db_pool_checked_in.set(pool.checkedin())
    db_pool_checked_out.set(pool.checkedout())
    db_pool_overflow.set(pool.overflow())
```

### Alert Thresholds

- **Pool utilization > 80%**: Scale pods or increase pool size
- **Pool timeout errors > 0**: Investigate slow queries or increase pool size
- **Overflow connections > 50% of max_overflow**: Sustained high load, increase `pool_size`

## References

- [SQLAlchemy Connection Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)
- [PostgreSQL Connection Management](https://www.postgresql.org/docs/current/runtime-config-connection.html)
- [AWS RDS Connection Management](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_Limits.html)
