#!/usr/bin/env bash
# TASK-095 Phase 4: Create and start a new agent container.
#
# Usage: ./scripts/create_agent.sh <agent-id> <host-port> <api-key> [openrouter-key]
#
# Creates:
#   /data/agents/<agent-id>/           — agent config root
#   /data/agents/<agent-id>/db/        — SQLite databases
#   /data/agents/<agent-id>/memory/    — memory files
#   /data/agents/<agent-id>/api_keys.json — API key for external access
#   /data/agents/<agent-id>/identity.yaml — (optional, copied from default)
#
# Then starts a Docker container named alive-agent-<agent-id>.

set -euo pipefail

AGENTS_ROOT="${AGENTS_ROOT:-/data/agents}"
IMAGE="${AGENT_IMAGE:-alive-engine:latest}"

usage() {
    echo "Usage: $0 <agent-id> <host-port> <api-key> [openrouter-key]"
    echo ""
    echo "  agent-id       Unique identifier (alphanumeric + hyphens)"
    echo "  host-port      Host port to map to container 8080"
    echo "  api-key        API key for external access (sk-live-...)"
    echo "  openrouter-key Optional OpenRouter API key (or set OPENROUTER_API_KEY env)"
    exit 1
}

if [[ $# -lt 3 ]]; then
    usage
fi

AGENT_ID="$1"
HOST_PORT="$2"
API_KEY="$3"
OR_KEY="${4:-${OPENROUTER_API_KEY:-}}"

# Validate agent ID (alphanumeric + hyphens only)
if [[ ! "$AGENT_ID" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ ]]; then
    echo "ERROR: agent-id must be alphanumeric with hyphens, got: $AGENT_ID"
    exit 1
fi

# Validate port is a number
if [[ ! "$HOST_PORT" =~ ^[0-9]+$ ]]; then
    echo "ERROR: host-port must be a number, got: $HOST_PORT"
    exit 1
fi

CONTAINER_NAME="alive-agent-${AGENT_ID}"
CONFIG_DIR="${AGENTS_ROOT}/${AGENT_ID}"

# Check if container already exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: Container ${CONTAINER_NAME} already exists."
    echo "  To restart: docker start ${CONTAINER_NAME}"
    echo "  To destroy: ./scripts/destroy_agent.sh ${AGENT_ID}"
    exit 1
fi

# Create directory structure
echo "[create_agent] Creating config directory: ${CONFIG_DIR}"
mkdir -p "${CONFIG_DIR}/db" "${CONFIG_DIR}/memory"

# Write API keys file
echo "[create_agent] Writing api_keys.json"
cat > "${CONFIG_DIR}/api_keys.json" <<KEYS
[
    {"key": "${API_KEY}", "name": "${AGENT_ID}", "rate_limit": 60}
]
KEYS

# Copy default identity if not present
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
if [[ ! -f "${CONFIG_DIR}/identity.yaml" ]] && [[ -f "${PROJECT_ROOT}/config/default_identity.yaml" ]]; then
    echo "[create_agent] Copying default identity.yaml"
    cp "${PROJECT_ROOT}/config/default_identity.yaml" "${CONFIG_DIR}/identity.yaml"
fi

# Build docker run command
DOCKER_ARGS=(
    -d
    --name "${CONTAINER_NAME}"
    --restart unless-stopped
    -v "${CONFIG_DIR}:/agent-config"
    -p "127.0.0.1:${HOST_PORT}:8080"
    -e "AGENT_ID=${AGENT_ID}"
    -e "AGENT_CONFIG_DIR=/agent-config"
)

# Add OpenRouter key if available
if [[ -n "$OR_KEY" ]]; then
    DOCKER_ARGS+=(-e "OPENROUTER_API_KEY=${OR_KEY}")
fi

# Add any extra env vars from .env file if present
if [[ -f "${CONFIG_DIR}/.env" ]]; then
    echo "[create_agent] Loading extra env vars from ${CONFIG_DIR}/.env"
    DOCKER_ARGS+=(--env-file "${CONFIG_DIR}/.env")
fi

echo "[create_agent] Starting container: ${CONTAINER_NAME} on port ${HOST_PORT}"
docker run "${DOCKER_ARGS[@]}" "${IMAGE}"

echo "[create_agent] Waiting for health check..."
for i in $(seq 1 10); do
    sleep 3
    if curl -sf "http://127.0.0.1:${HOST_PORT}/api/health" > /dev/null 2>&1; then
        echo "[create_agent] Agent '${AGENT_ID}' is healthy on port ${HOST_PORT}"
        exit 0
    fi
    echo "[create_agent] Attempt ${i}/10..."
done

echo "[create_agent] WARNING: Agent did not become healthy within 30s."
echo "  Check logs: docker logs ${CONTAINER_NAME}"
exit 1
