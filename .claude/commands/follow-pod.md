---
description: Follow Kubernetes pod logs for this backend service
argument-hint: <pod-selector>
---

# Follow Pod Logs - Backend Service

Stream logs from Kubernetes pods running this Python FastAPI backend service.

## Usage

```bash
/follow-pod <pod-selector>
```

## Arguments

- **pod-selector**: Pod name or label selector (e.g., `app=backend`, `backend-xyz123`)

## Examples

```bash
# Follow by label selector
/follow-pod app=backend-api

# Follow specific pod
/follow-pod backend-api-6d4f9c8b7f-k2m9p

# Follow with namespace
/follow-pod app=backend-api -n production
```

## What It Does

1. Finds pods matching selector
2. Streams logs with `kubectl logs -f`
3. Shows structured JSON logs
4. Highlights errors and warnings

## Useful Flags

```bash
# Last 100 lines
kubectl logs -f <pod> --tail=100

# Previous container (if crashed)
kubectl logs -f <pod> --previous

# With timestamps
kubectl logs -f <pod> --timestamps=true

# All containers in pod
kubectl logs -f <pod> --all-containers=true
```

## Debugging Production Issues

When investigating production problems:

1. **Capture logs**: `kubectl logs <pod> > issue.log`
2. **Check pod events**: `kubectl describe pod <pod>`
3. **Check resources**: `kubectl top pod <pod>`
4. **Previous logs** (if restarted): `kubectl logs <pod> --previous`

## Structured Logs

This backend uses structured JSON logging. Look for:

```json
{
  "timestamp": "2024-01-04T19:30:00Z",
  "level": "error",
  "event": "database_connection_failed",
  "error": "Connection timeout",
  "retry_count": 3
}
```

---

**Tip:** Use `jq` to parse JSON logs: `kubectl logs <pod> | jq '.level == "error"'`
