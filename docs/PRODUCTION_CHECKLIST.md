# Production Readiness Checklist

Pre-deployment verification checklist for redact_api. Complete all items before going live.

## Quick Status

| Category | Status |
|----------|--------|
| Security | ⬜ Not Started |
| Configuration | ⬜ Not Started |
| Database | ⬜ Not Started |
| Monitoring | ⬜ Not Started |
| Operations | ⬜ Not Started |
| Testing | ⬜ Not Started |

---

## Security

### Authentication & Authorization

- [ ] **Auth provider configured**: `AUTH_PROVIDER_TYPE` is NOT `none`
- [ ] **JWT algorithm secure**: Using RS256/ES256 (NOT HS256)
- [ ] **JWT public key set**: `JWT_PUBLIC_KEY` configured correctly
- [ ] **Issuer validated**: `AUTH_PROVIDER_ISSUER` matches token issuer
- [ ] **RBAC enforced**: Role-based access control enabled for sensitive operations
- [ ] **Tenant isolation enabled**: `ENFORCE_TENANT_ISOLATION=true` for multi-tenant deployments

### Network Security

- [ ] **TLS/SSL enabled**: All traffic uses HTTPS
- [ ] **CORS restricted**: `CORS_ALLOWED_ORIGINS` contains only production domains (no `*` or `localhost`)
- [ ] **Rate limiting active**: SlowAPI middleware configured with appropriate limits
- [ ] **No debug endpoints exposed**: `/docs` and `/openapi.json` disabled or protected in production
- [ ] **Health endpoints unauthenticated**: `/health`, `/metrics` accessible for monitoring

### Secrets Management

- [ ] **No secrets in code**: All secrets loaded from environment variables
- [ ] **No .env in production**: Using proper secrets management (Vault, AWS Secrets Manager, k8s secrets)
- [ ] **Database credentials rotated**: Initial credentials changed from defaults
- [ ] **API keys rotated**: External service API keys are production keys (not test keys)

### Vulnerability Checks

- [ ] **Dependencies scanned**: No known vulnerabilities (`uv pip audit` or similar)
- [ ] **Container image scanned**: Docker image passes security scan
- [ ] **SQL injection tests pass**: All 16 SQL injection tests passing
- [ ] **XSS tests pass**: All 12 XSS tests passing
- [ ] **Auth tests pass**: All 28 authentication tests passing

---

## Configuration

### Environment Variables

- [ ] **DATABASE_URL set**: Points to production database
- [ ] **ENVIRONMENT=production**: Not `local` or `development`
- [ ] **LOG_LEVEL=info**: Not `debug` in production
- [ ] **SQLALCHEMY_ECHO=false**: SQL logging disabled

### Storage Configuration

- [ ] **Storage provider configured**: `STORAGE_PROVIDER` matches deployment (local, azure, aws_s3, gcs)
- [ ] **Storage credentials set**: Appropriate credentials for chosen provider
- [ ] **Upload limits configured**: `MAX_FILE_SIZE_BYTES` set appropriately

### Startup Validation

- [ ] **Config validation passes**: Application starts without configuration errors
- [ ] **No warnings logged**: Address all configuration warnings from `settings.validate()`

---

## Database

### Migrations

- [ ] **All migrations applied**: `alembic upgrade head` completes successfully
- [ ] **Migration history clean**: `alembic history` shows expected migrations
- [ ] **No pending migrations**: `alembic current` matches `alembic heads`

### Connection Pool

- [ ] **Pool size appropriate**: `DB_POOL_SIZE` configured for expected load
- [ ] **Max overflow set**: `DB_MAX_OVERFLOW` allows burst capacity
- [ ] **Connection pre-ping enabled**: `DB_POOL_PRE_PING=true` for connection health
- [ ] **Pool recycle configured**: `DB_POOL_RECYCLE` prevents stale connections

### Backup & Recovery

- [ ] **Automated backups enabled**: Database backup schedule configured
- [ ] **Backup tested**: Successfully restored from backup
- [ ] **Point-in-time recovery**: WAL archiving enabled (PostgreSQL)
- [ ] **Backup retention policy**: Defined retention period for backups

### Performance

- [ ] **Indexes created**: All necessary indexes in place
- [ ] **Query performance acceptable**: No N+1 queries in critical paths
- [ ] **Connection pool metrics**: Monitoring pool utilization

---

## Monitoring & Alerting

### Metrics

- [ ] **Prometheus metrics exposed**: `/metrics` endpoint accessible
- [ ] **Metrics scraped**: Prometheus/Grafana configured to scrape metrics
- [ ] **Dashboard imported**: [Grafana dashboard](../k8s/grafana-dashboard.json) configured

### Alerting

- [ ] **Alert rules configured**: [Alerting rules](./alerting_rules.md) imported
- [ ] **Alert channels set**: PagerDuty/Slack/Email configured
- [ ] **On-call rotation**: Escalation policy defined

### Logging

- [ ] **Structured logging**: JSON logs in production
- [ ] **Log aggregation**: Logs forwarded to central system (ELK, Datadog, CloudWatch)
- [ ] **Log retention**: Retention policy configured
- [ ] **Request ID correlation**: `X-Request-ID` propagated through logs

---

## Operations

### Deployment

- [ ] **CI/CD pipeline**: Automated build and deploy configured
- [ ] **Rollback tested**: Verified rollback procedure works
- [ ] **Blue-green or canary**: Deployment strategy defined
- [ ] **Zero-downtime deploys**: Rolling update configured

### Health Checks

- [ ] **Liveness probe configured**: Container/pod restarts on failure
- [ ] **Readiness probe configured**: Traffic only sent when ready
- [ ] **Health check documented**: Load balancer health check configured

### Disaster Recovery

- [ ] **Recovery procedure documented**: Step-by-step recovery guide
- [ ] **Recovery tested**: Simulated failure and recovery
- [ ] **RTO/RPO defined**: Recovery time/point objectives documented
- [ ] **Incident response plan**: Escalation procedures defined

### Documentation

- [ ] **Runbook created**: Common operational tasks documented
- [ ] **Architecture diagram**: System architecture documented
- [ ] **API documentation**: OpenAPI spec accurate and complete

---

## Testing

### Test Suite

- [ ] **All tests passing**: `pytest` reports 100% pass rate
- [ ] **Coverage acceptable**: Minimum 80% code coverage
- [ ] **Security tests pass**: All security-specific tests green

### Load Testing

- [ ] **Load test completed**: System handles expected traffic
- [ ] **Performance baseline**: Response time benchmarks established
- [ ] **Capacity limits known**: Maximum throughput documented

### Integration Testing

- [ ] **External services tested**: Auth provider, storage, email integration verified
- [ ] **End-to-end flow tested**: Critical user journeys validated
- [ ] **Error handling tested**: Graceful degradation verified

---

## Pre-Launch Verification

Run these commands to verify readiness:

```bash
# Code quality checks
uv run ruff check .              # Expected: 0 violations
uv run mypy .                    # Expected: 0 errors

# Test suite
uv run pytest -v                 # Expected: 152/152 passing

# Security tests specifically
uv run pytest -v -k "security or sql_injection or xss or auth"

# Configuration validation
python -c "from redact_api.core.config import settings; print(settings.validate())"

# Database connectivity
python -c "
from redact_api.db.session import engine
import asyncio
async def test():
    async with engine.begin() as conn:
        await conn.execute('SELECT 1')
    print('Database OK')
asyncio.run(test())
"
```

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Developer | | | |
| Tech Lead | | | |
| Security | | | |
| Operations | | | |

---

## Post-Launch

After successful launch:

- [ ] **Monitor error rates**: Watch for increased 5xx errors
- [ ] **Monitor latency**: Check p95/p99 response times
- [ ] **Check alert noise**: Tune alerts if too noisy/quiet
- [ ] **Gather feedback**: Document issues for next deployment
- [ ] **Update runbook**: Add any new operational procedures

---

**Checklist Version**: 1.0.0
**Last Updated**: 2026-01-15
**Next Review**: Quarterly
