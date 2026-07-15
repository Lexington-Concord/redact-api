#!/usr/bin/env sh
set -eu

host="${HOST:-0.0.0.0}"
port="${PORT:-8000}"
project_slug="${PROJECT_SLUG:-redact_api}"
concurrency="${WORKER_CONCURRENCY:-10}"

# Two-process topology (redact-api#8): the TaskIQ worker consumes ingest/detect/apply
# jobs from RabbitMQ; the API serves HTTP + the /health(/live) probes. Single container,
# V1 topology -- background the worker, exec the API in the foreground so it is PID 1 and
# receives SIGTERM directly for graceful shutdown. Not a full process supervisor: on
# shutdown the container runtime tears down the whole cgroup, which also stops the
# backgrounded worker.
uv run taskiq worker "${project_slug}.tasks.worker:broker" \
  --workers "${concurrency}" &

exec uv run uvicorn "${project_slug}.main:app" \
  --host "${host}" \
  --port "${port}" \
  --log-config "${project_slug}/core/logging.yaml"
