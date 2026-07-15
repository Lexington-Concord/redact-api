#!/usr/bin/env sh
set -eu

host="${HOST:-0.0.0.0}"
port="${PORT:-8000}"
project_slug="${PROJECT_SLUG:-redact_api}"
concurrency="${WORKER_CONCURRENCY:-10}"

# Two-process topology (redact-api#8): the TaskIQ worker consumes ingest/detect/apply
# jobs from RabbitMQ; the API serves HTTP + the /health(/live) probes. Single container,
# both processes backgrounded as this shell's children so a trap can forward SIGTERM/SIGINT
# to both and wait for them to actually exit before the script itself exits. Why not `exec`
# uvicorn: a trap set before `exec` does not survive it (`exec` replaces the shell process
# image), so the worker would only be reachable via the container runtime tearing down the
# whole cgroup -- an abrupt kill, not a graceful one, that can hit apply_job/detect_job
# mid-PDF-burn or mid-transaction on every rolling deploy.
uv run taskiq worker "${project_slug}.tasks.worker:broker" \
  --workers "${concurrency}" &
worker_pid=$!

uv run uvicorn "${project_slug}.main:app" \
  --host "${host}" \
  --port "${port}" \
  --log-config "${project_slug}/core/logging.yaml" &
uvicorn_pid=$!

# Forward SIGTERM/SIGINT to both children and wait for each to exit before this script
# (and therefore the container) is considered stopped. Idempotent: on a signal, the trap
# below runs this and does the kill+wait; the fallthrough call after `wait` below then
# repeats it (a no-op if the trap already reaped both children) to cover the case where
# uvicorn exits on its own (crash/normal exit) rather than via a forwarded signal.
term_handler() {
  kill -TERM "$uvicorn_pid" 2>/dev/null || true
  kill -TERM "$worker_pid" 2>/dev/null || true
  wait "$uvicorn_pid" 2>/dev/null || true
  wait "$worker_pid" 2>/dev/null || true
}
trap term_handler TERM INT

# `set -e` would otherwise abort the script the instant `wait` returns uvicorn's exit
# status if it's non-zero, skipping the worker cleanup below -- so disable it just for the
# wait and propagate the real exit code manually.
set +e
wait "$uvicorn_pid"
exit_code=$?
set -e

term_handler
exit "$exit_code"
