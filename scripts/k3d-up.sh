#!/usr/bin/env bash
set -euo pipefail

# Source .env if it exists (for CLUSTER_NAME, NAMESPACE overrides)
if [ -f .env ]; then
  set -a; source .env; set +a
fi

cluster_name="${CLUSTER_NAME:-redact_api}"
namespace="${NAMESPACE:-dev}"

# Validate names (RFC 1123 DNS label: lowercase alphanumeric and hyphens only)
validate_k8s_name() {
  local name="$1"
  local type="$2"
  if [[ ! "$name" =~ ^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$ ]]; then
    echo "ERROR: Invalid ${type} '${name}'" >&2
    echo "  Must contain only lowercase letters, numbers, and hyphens." >&2
    echo "  Must start and end with alphanumeric character." >&2
    echo "  Cannot contain dots (common mistake with domain names)." >&2
    exit 1
  fi
}

validate_k8s_name "$cluster_name" "cluster name"
validate_k8s_name "$namespace" "namespace"

if ! command -v k3d >/dev/null 2>&1; then
  echo "k3d is required but not installed." >&2
  exit 1
fi

if ! k3d cluster list | grep -q "^${cluster_name}\\b"; then
  # Map host 8080->80 and 8443->443 to avoid conflicts with host services
  k3d cluster create "${cluster_name}" --agents 1 --servers 1 \
    -p "8080:80@loadbalancer" \
    -p "8443:443@loadbalancer"
fi

for _ in $(seq 1 30); do
  if kubectl get namespaces >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

kubectl create namespace "${namespace}" >/dev/null 2>&1 || true
