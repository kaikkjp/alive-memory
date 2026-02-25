#!/usr/bin/env bash
# TASK-095 Phase 4: Stop and remove an agent container.
#
# Usage: ./scripts/destroy_agent.sh <agent-id> [--purge]
#
# Without --purge: stops container and removes it, keeps data.
# With --purge: also deletes /data/agents/<agent-id>/ (irreversible).

set -euo pipefail

AGENTS_ROOT="${AGENTS_ROOT:-/data/agents}"

usage() {
    echo "Usage: $0 <agent-id> [--purge]"
    echo ""
    echo "  --purge    Also delete all agent data (DB, memory, config)"
    exit 1
}

if [[ $# -lt 1 ]]; then
    usage
fi

AGENT_ID="$1"
PURGE=false
if [[ "${2:-}" == "--purge" ]]; then
    PURGE=true
fi

CONTAINER_NAME="alive-agent-${AGENT_ID}"
CONFIG_DIR="${AGENTS_ROOT}/${AGENT_ID}"

# Stop container if running
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "[destroy_agent] Stopping container: ${CONTAINER_NAME}"
    docker stop "${CONTAINER_NAME}"
fi

# Remove container if exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "[destroy_agent] Removing container: ${CONTAINER_NAME}"
    docker rm "${CONTAINER_NAME}"
else
    echo "[destroy_agent] Container ${CONTAINER_NAME} not found (already removed?)"
fi

if [[ "$PURGE" == true ]]; then
    if [[ -d "$CONFIG_DIR" ]]; then
        echo "[destroy_agent] PURGING data directory: ${CONFIG_DIR}"
        rm -rf "${CONFIG_DIR}"
        echo "[destroy_agent] Data purged."
    else
        echo "[destroy_agent] No data directory found at ${CONFIG_DIR}"
    fi
else
    echo "[destroy_agent] Data preserved at ${CONFIG_DIR}"
    echo "  To also delete data: $0 ${AGENT_ID} --purge"
fi

echo "[destroy_agent] Done."
