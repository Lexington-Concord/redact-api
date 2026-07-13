#!/bin/bash
# Export OpenAPI spec to shared workspace location
# Run this after API changes to update the contract

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SPECS_DIR="${PROJECT_DIR}/../specs"

mkdir -p "$SPECS_DIR"

echo "Generating OpenAPI spec..."
cd "$PROJECT_DIR"

# Use Python to generate spec without running server
uv run python -c "
import json
from redact_api.main import app
spec = app.openapi()
print(json.dumps(spec, indent=2))
" > "$SPECS_DIR/openapi.json"

echo "OpenAPI spec exported to $SPECS_DIR/openapi.json"
