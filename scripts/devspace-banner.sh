#!/usr/bin/env bash
# Usage: devspace-banner.sh <MODE> <CLUSTER> [SERVICE_INFO]
# Example: devspace-banner.sh STANDALONE meta-workspace "Deploying: all"
# Example: devspace-banner.sh DEPENDENCY meta-workspace "Service: api"

MODE="${1:-UNKNOWN}"
CLUSTER="${2:-unknown}"
SERVICE_INFO="${3:-}"

echo "================================================"
echo "DevSpace Mode: $MODE"
if [ "$MODE" = "DEPENDENCY" ]; then
    echo "Parent Cluster: $CLUSTER"
else
    echo "Cluster: $CLUSTER"
    echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
fi
[ -n "$SERVICE_INFO" ] && echo "$SERVICE_INFO"
echo "================================================"
