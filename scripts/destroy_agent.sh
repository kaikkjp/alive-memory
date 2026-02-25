#!/bin/bash
# destroy_agent.sh — Stop and remove an ALIVE agent
#
# Usage: ./scripts/destroy_agent.sh <agent_id> [--purge]
#   --purge: also delete agent data (DB, memory, config). IRREVERSIBLE.

set -euo pipefail

AGENT_ID="${1:?Usage: destroy_agent.sh <agent_id> [--purge]}"
PURGE="${2:-}"

DATA_DIR="/data/alive-agents"
AGENT_DIR="$DATA_DIR/$AGENT_ID"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTAINER_NAME="alive-agent-${AGENT_ID}"

# Check container exists
if ! docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: Agent '$AGENT_ID' not found (no container '${CONTAINER_NAME}')"
    exit 1
fi

echo "Destroying agent: $AGENT_ID"

# Stop and remove container
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true
echo "  Container removed."

# Update nginx routes
if [ -f "$SCRIPT_DIR/nginx_regen.sh" ]; then
    echo "  Updating nginx routes..."
    bash "$SCRIPT_DIR/nginx_regen.sh"
fi

# Purge data if requested
if [ "$PURGE" = "--purge" ]; then
    if [ -d "$AGENT_DIR" ]; then
        echo "  ⚠️  Purging agent data: $AGENT_DIR"
        rm -rf "$AGENT_DIR"
        echo "  Data purged."
    fi
else
    echo "  Data preserved at: $AGENT_DIR"
    echo "  To also delete data: ./scripts/destroy_agent.sh $AGENT_ID --purge"
fi

echo ""
echo "Agent '$AGENT_ID' destroyed."
