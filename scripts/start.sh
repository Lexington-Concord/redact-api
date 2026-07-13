#!/usr/bin/env sh
set -eu

host="${HOST:-0.0.0.0}"
port="${PORT:-8000}"
project_slug="${PROJECT_SLUG:-redact_api}"

exec uv run uvicorn "${project_slug}.main:app" \
  --host "${host}" \
  --port "${port}" \
  --log-config "${project_slug}/core/logging.yaml"
