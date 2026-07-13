# Deployment Guide

Step-by-step guide for deploying redact_api to production environments.

## Prerequisites

Before deploying, ensure you have:

- Docker installed and configured
- Access to a container registry (Docker Hub, ECR, GCR, ACR)
- PostgreSQL database provisioned
- (Optional) Kubernetes cluster for k8s deployment
- Environment variables configured (see [Configuration Guide](../CONFIGURATION-GUIDE.md))

## Deployment Options

| Method | Best For | Complexity |
|--------|----------|------------|
| [Docker Compose](#docker-compose-deployment) | Single server, small teams | Low |
| [Kubernetes](#kubernetes-deployment) | Production, scaling, HA | Medium |
| [Manual](#manual-deployment) | Debugging, development VMs | Low |

---

## Docker Compose Deployment

### 1. Build the Container Image

```bash
# Build production image
docker build -t redact_api:latest .

# Tag for registry (replace with your registry)
docker tag redact_api:latest your-registry.com/redact_api:v1.0.0

# Push to registry
docker push your-registry.com/redact_api:v1.0.0
```

### 2. Create docker-compose.prod.yml

```yaml
version: '3.8'

services:
  api:
    image: your-registry.com/redact_api:v1.0.0
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - ENVIRONMENT=production
      - LOG_LEVEL=info
      - AUTH_PROVIDER_TYPE=${AUTH_PROVIDER_TYPE}
      - AUTH_PROVIDER_URL=${AUTH_PROVIDER_URL}
      - AUTH_PROVIDER_ISSUER=${AUTH_PROVIDER_ISSUER}
      - JWT_PUBLIC_KEY=${JWT_PUBLIC_KEY}
      - CORS_ALLOWED_ORIGINS=${CORS_ALLOWED_ORIGINS}
      - STORAGE_PROVIDER=${STORAGE_PROVIDER}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
```

### 3. Deploy

```bash
# Create .env file with production values
cp .env.example .env.prod
# Edit .env.prod with your production values

# Deploy
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d

# Check status
docker compose -f docker-compose.prod.yml ps

# View logs
docker compose -f docker-compose.prod.yml logs -f api
```

---

## Kubernetes Deployment

### 1. Build and Push Image

```bash
# Build image
docker build -t your-registry.com/redact_api:v1.0.0 .

# Push to registry
docker push your-registry.com/redact_api:v1.0.0
```

### 2. Create Kubernetes Secret

```bash
# Create namespace
kubectl create namespace redact_api

# Create secret from .env file
kubectl create secret generic redact_api-secrets \
  --from-env-file=.env.prod \
  --namespace redact_api

# Or create secret manually
kubectl create secret generic redact_api-secrets \
  --namespace redact_api \
  --from-literal=DATABASE_URL='postgresql+asyncpg://user:pass@db:5432/app' \
  --from-literal=JWT_PUBLIC_KEY='-----BEGIN PUBLIC KEY-----...'
```

### 3. Create Deployment Manifest

Save as `k8s/deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redact_api
  namespace: redact_api
  labels:
    app: redact_api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: redact_api
  template:
    metadata:
      labels:
        app: redact_api
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      containers:
        - name: api
          image: your-registry.com/redact_api:v1.0.0
          ports:
            - containerPort: 8000
          envFrom:
            - secretRef:
                name: redact_api-secrets
          env:
            - name: ENVIRONMENT
              value: "production"
            - name: LOG_LEVEL
              value: "info"
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2000m"
              memory: "2Gi"
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 30
          securityContext:
            runAsNonRoot: true
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
---
apiVersion: v1
kind: Service
metadata:
  name: redact_api
  namespace: redact_api
spec:
  selector:
    app: redact_api
  ports:
    - port: 80
      targetPort: 8000
  type: ClusterIP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: redact_api
  namespace: redact_api
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
    - hosts:
        - api.example.com
      secretName: redact_api-tls
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: redact_api
                port:
                  number: 80
```

### 4. Apply Manifests

```bash
# Apply database manifests (if using in-cluster postgres)
kubectl apply -f k8s/postgres-secret.yaml -n redact_api
kubectl apply -f k8s/postgres-service.yaml -n redact_api
kubectl apply -f k8s/postgres-statefulset.yaml -n redact_api

# Wait for database to be ready
kubectl wait --for=condition=ready pod -l app=postgres -n redact_api --timeout=120s

# Run database migrations
kubectl run migrations --rm -it --restart=Never \
  --image=your-registry.com/redact_api:v1.0.0 \
  --namespace=redact_api \
  --env-from=secret/redact_api-secrets \
  -- alembic upgrade head

# Apply application manifests
kubectl apply -f k8s/deployment.yaml

# Check rollout status
kubectl rollout status deployment/redact_api -n redact_api

# Verify pods are running
kubectl get pods -n redact_api
```

### 5. Verify Deployment

```bash
# Check pod logs
kubectl logs -f deployment/redact_api -n redact_api

# Test health endpoint (via port-forward)
kubectl port-forward svc/redact_api 8000:80 -n redact_api
curl http://localhost:8000/health

# Check metrics
curl http://localhost:8000/metrics
```

---

## Manual Deployment

For debugging or non-containerized deployments.

### 1. Install Dependencies

```bash
# Install Python 3.13+
# Install uv package manager

# Clone and setup
git clone <your-repo> redact_api
cd redact_api
uv sync --frozen
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with production values
```

### 3. Run Database Migrations

```bash
uv run alembic upgrade head
```

### 4. Start Application

```bash
# Production server with uvicorn
uv run uvicorn redact_api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --access-log \
  --log-level info
```

### 5. Configure Reverse Proxy (nginx)

```nginx
upstream redact_api {
    server 127.0.0.1:8000;
}

server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    location / {
        proxy_pass http://redact_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Health check endpoint (no auth)
    location /health {
        proxy_pass http://redact_api/health;
    }
}
```

---

## Database Migrations in Production

### CI/CD Pipeline Migration

Add this step to your CI/CD pipeline:

```yaml
# GitHub Actions example
- name: Run Database Migrations
  env:
    DATABASE_URL: ${{ secrets.DATABASE_URL }}
  run: |
    uv run alembic upgrade head
```

### Kubernetes Job for Migrations

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: redact_api-migration
  namespace: redact_api
spec:
  template:
    spec:
      containers:
        - name: migration
          image: your-registry.com/redact_api:v1.0.0
          command: ["alembic", "upgrade", "head"]
          envFrom:
            - secretRef:
                name: redact_api-secrets
      restartPolicy: Never
  backoffLimit: 3
```

Apply with:
```bash
kubectl apply -f k8s/migration-job.yaml
kubectl wait --for=condition=complete job/redact_api-migration -n redact_api
```

---

## Health Check Configuration

The application exposes health endpoints:

| Endpoint | Purpose | Auth Required |
|----------|---------|---------------|
| `/health` | Basic liveness check | No |
| `/health/ready` | Readiness (DB connected) | No |
| `/metrics` | Prometheus metrics | No |

### Load Balancer Configuration

Configure your load balancer health check:

- **Path**: `/health`
- **Port**: 8000
- **Interval**: 30 seconds
- **Timeout**: 10 seconds
- **Healthy threshold**: 2
- **Unhealthy threshold**: 3

---

## TLS/SSL Configuration

### Option 1: Let's Encrypt with cert-manager (Kubernetes)

```yaml
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.0/cert-manager.yaml

# Create ClusterIssuer
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your-email@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            class: nginx
```

### Option 2: Manual Certificate

```bash
# Generate certificate (or use existing)
# Place in /etc/ssl/certs/

# Update nginx config to use certificates
ssl_certificate /etc/ssl/certs/api.example.com.crt;
ssl_certificate_key /etc/ssl/private/api.example.com.key;
```

---

## Rollback Procedure

### Kubernetes Rollback

```bash
# View rollout history
kubectl rollout history deployment/redact_api -n redact_api

# Rollback to previous version
kubectl rollout undo deployment/redact_api -n redact_api

# Rollback to specific revision
kubectl rollout undo deployment/redact_api --to-revision=2 -n redact_api
```

### Docker Compose Rollback

```bash
# Pull previous image version
docker pull your-registry.com/redact_api:v0.9.0

# Update docker-compose.prod.yml with previous version
# Redeploy
docker compose -f docker-compose.prod.yml up -d
```

### Database Rollback

```bash
# Check current migration
uv run alembic current

# Rollback one migration
uv run alembic downgrade -1

# Rollback to specific revision
uv run alembic downgrade <revision_id>
```

**Warning**: Database rollbacks may cause data loss. Always backup before rolling back migrations.

---

## Monitoring & Logging

### Prometheus Metrics

The application exposes metrics at `/metrics`:

- `http_requests_total` - Total HTTP requests
- `http_request_duration_seconds` - Request latency histogram
- `db_connection_pool_size` - Database connection pool status

### Log Aggregation

Logs are output in JSON format (ECS-compatible) when `ENVIRONMENT=production`:

```json
{
  "@timestamp": "2024-01-15T10:30:00.000Z",
  "log.level": "info",
  "message": "Request completed",
  "request_id": "abc-123",
  "user_id": "user-456",
  "org_id": "org-789",
  "http.request.method": "GET",
  "http.response.status_code": 200
}
```

Configure log forwarding to your preferred platform (ELK, Datadog, CloudWatch).

---

## Troubleshooting

### Application Won't Start

```bash
# Check configuration validation errors
docker logs redact_api

# Common issues:
# - DATABASE_URL not set or invalid
# - AUTH_PROVIDER_URL required when AUTH_PROVIDER_TYPE != none
# - STORAGE_* variables required for cloud storage providers
```

### Database Connection Failures

```bash
# Test database connectivity
docker exec redact_api python -c "
from redact_api.core.config import settings
print(f'Connecting to: {settings.database_url.split(\"@\")[-1]}')
"

# Check connection pool status via metrics
curl http://localhost:8000/metrics | grep db_
```

### Authentication Errors

```bash
# Verify JWT configuration
# Check AUTH_PROVIDER_ISSUER matches token issuer
# Verify JWT_PUBLIC_KEY is correctly formatted (PEM)

# Test token validation manually
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/users/me
```

---

## Next Steps

After deployment:

1. [ ] Run [Production Checklist](./PRODUCTION_CHECKLIST.md)
2. [ ] Configure [Alerting Rules](./alerting_rules.md)
3. [ ] Import [Grafana Dashboard](../k8s/grafana-dashboard.json)
4. [ ] Set up log aggregation
5. [ ] Configure backup schedule

---

**Last Updated**: 2026-01-15
**Maintainer**: redact_api team
