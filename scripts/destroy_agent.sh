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

echo "Destroying agent: $AGENT_ID"

# Always clean up gateway token first (even if container doesn't exist —
# token may have been registered before container creation failed)
TOKENS_FILE="${GATEWAY_TOKENS_PATH:-/data/alive-agents/agent_tokens.json}"
if [ -f "$TOKENS_FILE" ]; then
    NEW_TOKENS="$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
data.pop(sys.argv[2], None)
print(json.dumps(data, indent=2))
" "$TOKENS_FILE" "$AGENT_ID" 2>/dev/null || cat "$TOKENS_FILE")"
    echo "$NEW_TOKENS" > "$TOKENS_FILE"
    echo "  Removed agent token from $TOKENS_FILE"
fi

# Stop and remove container (if it exists)
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    echo "  Container removed."
else
    echo "  No container found (already removed or never created)."
fi

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
