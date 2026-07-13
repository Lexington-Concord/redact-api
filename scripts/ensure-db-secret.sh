#!/usr/bin/env bash
set -euo pipefail

# Idempotent database secret generator
# Creates postgres-secret in the namespace if it doesn't exist
# Uses cryptographically secure random password

NAMESPACE="${NAMESPACE:-warren-enterprises-ltd}"
SECRET_NAME="postgres-secret"

# Check if secret already exists
if kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" &>/dev/null; then
  echo "Secret $SECRET_NAME already exists in $NAMESPACE"
  exit 0
fi

# Generate credentials
POSTGRES_USER="${POSTGRES_USER:-app}"
POSTGRES_DB="${POSTGRES_DB:-app}"
POSTGRES_PASSWORD="$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)"

# Create secret
kubectl create secret generic "$SECRET_NAME" \
  --namespace="$NAMESPACE" \
  --from-literal=POSTGRES_USER="$POSTGRES_USER" \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=POSTGRES_DB="$POSTGRES_DB"

echo "Created secret $SECRET_NAME with generated password"
