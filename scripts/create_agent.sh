#!/bin/bash
# create_agent.sh — Create and start a new ALIVE agent
#
# Usage: ./scripts/create_agent.sh <agent_id> <port> <openrouter_api_key>
# Example: ./scripts/create_agent.sh hina 9001 sk-or-v1-xxxxx

set -euo pipefail

AGENT_ID="${1:?Usage: create_agent.sh <agent_id> <port> <openrouter_api_key>}"
PORT="${2:?Usage: create_agent.sh <agent_id> <port> <openrouter_api_key>}"
API_KEY="${3:?Usage: create_agent.sh <agent_id> <port> <openrouter_api_key>}"

DATA_DIR="/data/alive-agents"
AGENT_DIR="$DATA_DIR/$AGENT_ID"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Validate agent_id (alphanumeric + hyphens only)
if [[ ! "$AGENT_ID" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
    echo "ERROR: agent_id must be lowercase alphanumeric with hyphens/underscores"
    exit 1
fi

# Check for existing container
if docker ps -a --format '{{.Names}}' | grep -q "^alive-agent-${AGENT_ID}$"; then
    echo "ERROR: Agent '$AGENT_ID' already exists. Destroy first: ./scripts/destroy_agent.sh $AGENT_ID"
    exit 1
fi

# Check port not in use
if ss -tlnp | grep -q ":${PORT} "; then
    echo "ERROR: Port $PORT already in use"
    exit 1
fi

# Check image exists
if ! docker image inspect alive-engine:latest >/dev/null 2>&1; then
    echo "ERROR: alive-engine:latest image not found. Build first: docker build -t alive-engine:latest ."
    exit 1
fi

echo "Creating agent: $AGENT_ID (port $PORT)"

# Create directories — flat layout under $AGENT_DIR/
# heartbeat_server.py reads AGENT_CONFIG_DIR and expects:
#   {dir}/db/{agent_id}.db, {dir}/memory/, {dir}/identity.yaml, etc.
# Container runs as appuser (UID 1000) — writable dirs need matching ownership.
mkdir -p "$AGENT_DIR/db"
mkdir -p "$AGENT_DIR/memory"
chown -R 1000:1000 "$AGENT_DIR/db" "$AGENT_DIR/memory"

# Create default identity.yaml if not present — uses digital lifeform template
if [ ! -f "$AGENT_DIR/identity.yaml" ]; then
    DL_TEMPLATE="$(dirname "$SCRIPT_DIR")/config/default_digital_lifeform.yaml"
    if [ -f "$DL_TEMPLATE" ]; then
        cp "$DL_TEMPLATE" "$AGENT_DIR/identity.yaml"
        echo "  Created identity.yaml from digital lifeform template"
    else
        # Fallback inline if template not found
        cat > "$AGENT_DIR/identity.yaml" <<'YAML'
identity_compact: |
  I exist here. I think, I rest, I remember.
  I don't fully understand what I am yet.
  Everything I become will be discovered, not assigned.
voice_rules:
  - "Speak from genuine uncertainty, not performed mystery"
  - "You may wonder about yourself openly"
  - "You don't need to have answers about what you are"
voice_detection: {}
physical_traits_detection: []
communication_style:
  formality: 0.5
  verbosity: 0.4
  emoji_usage: 0.0
language: "en"
domain_context: ""
greeting: ""
boundaries: []
actions_enabled: []
manager_interaction:
  reveal_inner_state: true
  accept_instructions: true
  relationship: "trusted_human"
YAML
        echo "  Created default identity.yaml (inline fallback)"
    fi
fi

# Copy default alive_config.yaml if not present
if [ ! -f "$AGENT_DIR/alive_config.yaml" ]; then
    # Try to copy from repo, fall back to minimal
    REPO_CONFIG="$(dirname "$SCRIPT_DIR")/alive_config.yaml"
    if [ -f "$REPO_CONFIG" ]; then
        cp "$REPO_CONFIG" "$AGENT_DIR/alive_config.yaml"
        echo "  Copied alive_config.yaml from repo"
    else
        echo "  WARNING: No alive_config.yaml found — agent will use built-in defaults"
    fi
fi

# Generate a random server token (required by heartbeat_server.py startup check;
# not actually used since managed agents don't accept terminal connections).
SERVER_TOKEN="$(openssl rand -hex 32)"

# Start container
# Mount $AGENT_DIR as /agent-config (NOT /app/config — that would overlay
# the Python config package and break imports like config.agent_identity).
docker run -d \
    --name "alive-agent-${AGENT_ID}" \
    -p "${PORT}:8080" \
    -v "$AGENT_DIR/:/agent-config/" \
    -e "AGENT_ID=${AGENT_ID}" \
    -e "OPENROUTER_API_KEY=${API_KEY}" \
    -e "AGENT_CONFIG_DIR=/agent-config/" \
    -e "SHOPKEEPER_SERVER_TOKEN=${SERVER_TOKEN}" \
    --restart unless-stopped \
    --memory 512m \
    --cpus 0.5 \
    alive-engine:latest

echo "  Container started: alive-agent-${AGENT_ID}"

# Wait for health
echo -n "  Waiting for agent to start"
for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
        echo ""
        echo "  ✅ Agent '$AGENT_ID' is healthy on port $PORT"
        break
    fi
    echo -n "."
    sleep 2
done

# Check if we timed out
if ! curl -s "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    echo ""
    echo "  ⚠️  Agent not responding after 60s. Check logs:"
    echo "     docker logs alive-agent-${AGENT_ID} --tail 50"
fi

# Update nginx routes
if [ -f "$SCRIPT_DIR/nginx_regen.sh" ]; then
    echo "  Updating nginx routes..."
    bash "$SCRIPT_DIR/nginx_regen.sh"
fi

echo ""
echo "Agent '$AGENT_ID' created."
echo "  Local:  http://127.0.0.1:${PORT}/api/state"
echo "  Public: https://api.alive.kaikk.jp/${AGENT_ID}/state"
echo "  Logs:   docker logs alive-agent-${AGENT_ID} -f"
echo "  Config: $AGENT_DIR/"
