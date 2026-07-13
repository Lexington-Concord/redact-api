#!/usr/bin/env bash
set -euo pipefail

# Source .env if it exists (for CLUSTER_NAME override)
if [ -f .env ]; then
  set -a; source .env; set +a
fi

cluster_name="${CLUSTER_NAME:-fastapi-template}"

if ! command -v k3d >/dev/null 2>&1; then
  echo "k3d is required but not installed." >&2
  exit 1
fi

# Delete the cluster
k3d cluster delete "${cluster_name}" 2>/dev/null || true

# Remove the kubectl context (so DevSpace doesn't try to use it)
kubectl config delete-context "k3d-${cluster_name}" 2>/dev/null || true
kubectl config delete-cluster "k3d-${cluster_name}" 2>/dev/null || true
kubectl config delete-user "admin@k3d-${cluster_name}" 2>/dev/null || true

# Unset current context if it was pointing to the deleted cluster
current_context=$(kubectl config current-context 2>/dev/null || echo "")
if [[ "$current_context" == "k3d-${cluster_name}" ]] || [[ -z "$current_context" ]]; then
  kubectl config unset current-context 2>/dev/null || true
fi

# Clear DevSpace cache (forces fresh context detection on next run)
rm -f .devspace/cache.yaml
