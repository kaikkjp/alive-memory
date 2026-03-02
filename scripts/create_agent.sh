#!/bin/bash
# create_agent.sh — Create and start a new ALIVE agent
#
# Usage: ./scripts/create_agent.sh [--force] [--validate] <agent_id> <port> <openrouter_api_key>
# Example: ./scripts/create_agent.sh hina 9001 sk-or-v1-xxxxx
#          ./scripts/create_agent.sh --force hina 9001 sk-or-v1-xxxxx
#          ./scripts/create_agent.sh --validate hina 9001 sk-or-v1-xxxxx
#
# Flags:
#   --force     If container exists, stop and recreate (preserves db/ and memory/)
#   --validate  Run preflight checks without starting the container

set -euo pipefail

# Parse flags
FORCE=false
VALIDATE=false
GATEWAY=false
while [[ "${1:-}" == --* ]]; do
    case "$1" in
        --force)    FORCE=true; shift ;;
        --validate) VALIDATE=true; shift ;;
        --gateway)  GATEWAY=true; shift ;;
        *)          echo "ERROR: Unknown flag: $1"; exit 1 ;;
    esac
done

AGENT_ID="${1:?Usage: create_agent.sh [--force] [--validate] <agent_id> <port> <openrouter_api_key>}"
PORT="${2:?Usage: create_agent.sh [--force] [--validate] <agent_id> <port> <openrouter_api_key>}"
API_KEY="${3:?Usage: create_agent.sh [--force] [--validate] <agent_id> <port> <openrouter_api_key>}"

DATA_DIR="/data/alive-agents"
AGENT_DIR="$DATA_DIR/$AGENT_ID"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTAINER_NAME="alive-agent-${AGENT_ID}"

# Validate agent_id (alphanumeric + hyphens only)
if [[ ! "$AGENT_ID" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
    echo "ERROR: agent_id must be lowercase alphanumeric with hyphens/underscores"
    exit 1
fi

# Check image exists BEFORE any teardown (don't destroy a working container
# only to discover the image is missing)
if ! docker image inspect alive-engine:latest >/dev/null 2>&1; then
    echo "ERROR: alive-engine:latest image not found. Build first: docker build -t alive-engine:latest ."
    exit 1
fi

# Handle existing container
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    if [ "$FORCE" = true ]; then
        echo "  --force: stopping existing container '$CONTAINER_NAME'"
        docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
        docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
    elif [ "$VALIDATE" = true ]; then
        # For --validate with existing container, we can run preflight inside
        # the existing container without disturbing it. See below.
        :
    else
        echo "ERROR: Agent '$AGENT_ID' already exists. Destroy first: ./scripts/destroy_agent.sh $AGENT_ID"
        echo "  Or use --force to replace it (preserves db/ and memory/)"
        exit 1
    fi
fi

# Check port not in use (AFTER teardown — in --force mode the old container was using this port)
if [ "$VALIDATE" != true ]; then
    if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
        echo "ERROR: Port $PORT already in use"
        exit 1
    fi
fi

# --validate: run preflight checks and exit
if [ "$VALIDATE" = true ]; then
    echo "Validating agent: $AGENT_ID (port $PORT)"

    # Check if container already exists and is running
    WAS_RUNNING=false
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        WAS_RUNNING=true
    fi

    if [ "$WAS_RUNNING" = true ]; then
        # Run preflight inside the already-running container
        echo "  Container is running — validating inside existing container"
        docker exec "$CONTAINER_NAME" \
            python -c "from preflight import run_preflight; import sys; sys.exit(0 if run_preflight() else 1)"
        PREFLIGHT_RC=$?
    elif docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        # Container exists but stopped — start temporarily
        echo "  Starting stopped container for validation..."
        docker start "$CONTAINER_NAME" >/dev/null 2>&1
        sleep 2
        # Capture exit code without triggering set -e, then always stop
        docker exec "$CONTAINER_NAME" \
            python -c "from preflight import run_preflight; import sys; sys.exit(0 if run_preflight() else 1)" \
            && PREFLIGHT_RC=0 || PREFLIGHT_RC=$?
        echo "  Stopping container (was not running before validate)"
        docker stop "$CONTAINER_NAME" >/dev/null 2>&1
    else
        # No container — create a temporary one for validation
        echo "  No container found — creating temporary container for validation"
        mkdir -p "$AGENT_DIR/db" "$AGENT_DIR/memory"
        SERVER_TOKEN="$(openssl rand -hex 32)"
        docker run --rm --name "${CONTAINER_NAME}-validate" \
            -v "$AGENT_DIR/:/agent-config/" \
            -e "AGENT_ID=${AGENT_ID}" \
            -e "OPENROUTER_API_KEY=${API_KEY}" \
            -e "AGENT_CONFIG_DIR=/agent-config/" \
            -e "SHOPKEEPER_SERVER_TOKEN=${SERVER_TOKEN}" \
            alive-engine:latest \
            python -c "from preflight import run_preflight; import sys; sys.exit(0 if run_preflight() else 1)"
        PREFLIGHT_RC=$?
    fi

    exit "$PREFLIGHT_RC"
fi

echo "Creating agent: $AGENT_ID (port $PORT)"

# Create directories — flat layout under $AGENT_DIR/
# heartbeat_server.py reads AGENT_CONFIG_DIR and expects:
#   {dir}/db/{agent_id}.db, {dir}/memory/, {dir}/identity.yaml, etc.
mkdir -p "$AGENT_DIR/db"
mkdir -p "$AGENT_DIR/memory"

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
world:
  has_physical_space: false
  framing: |
    You exist in a digital space. People reach you through messages.
    You have no physical form, no room, no objects. Your world is
    internal — thoughts, words, connections.
  body_states: [present, thinking, resting]
  gaze_directions: [inward, outward, unfocused]
  expressions: [neutral, thinking, low, curious, uncertain]
YAML
        echo "  Created default identity.yaml (inline fallback)"
    fi
fi

# Copy default alive_config.yaml if not present
if [ ! -f "$AGENT_DIR/alive_config.yaml" ]; then
    # Try to copy from repo, fall back to minimal
    REPO_CONFIG="$(dirname "$SCRIPT_DIR")/engine/alive_config.yaml"
    if [ -f "$REPO_CONFIG" ]; then
        cp "$REPO_CONFIG" "$AGENT_DIR/alive_config.yaml"
        echo "  Copied alive_config.yaml from repo"
    else
        echo "  WARNING: No alive_config.yaml found — agent will use built-in defaults"
    fi
fi

# Chown entire agent dir AFTER all files are created — container runs as
# appuser (UID 1000) and needs write access to identity.yaml, api_keys.json, etc.
chown -R 1000:1000 "$AGENT_DIR"

# Generate a random server token (required by heartbeat_server.py startup check;
# not actually used since managed agents don't accept terminal connections).
SERVER_TOKEN="$(openssl rand -hex 32)"

# ── Gateway mode: generate agent token and register ──
GATEWAY_AGENT_TOKEN=""
if [ "$GATEWAY" = true ]; then
    GATEWAY_AGENT_TOKEN="$(openssl rand -hex 32)"
    TOKENS_FILE="${GATEWAY_TOKENS_PATH:-/data/alive-agents/agent_tokens.json}"

    # Atomic token registration: read → merge → write via temp file + rename
    if [ -f "$TOKENS_FILE" ]; then
        CURRENT="$(cat "$TOKENS_FILE")"
    else
        CURRENT="{}"
        mkdir -p "$(dirname "$TOKENS_FILE")"
    fi

    # Merge new token using python (available in all alive environments)
    NEW_TOKENS="$(python3 -c "
import json, sys
data = json.loads(sys.argv[1])
data[sys.argv[2]] = sys.argv[3]
print(json.dumps(data, indent=2))
" "$CURRENT" "$AGENT_ID" "$GATEWAY_AGENT_TOKEN")"

    TMPFILE="$(mktemp "${TOKENS_FILE}.XXXXXX")"
    echo "$NEW_TOKENS" > "$TMPFILE"
    mv "$TMPFILE" "$TOKENS_FILE"
    echo "  Registered agent token in $TOKENS_FILE"
fi

# Start container
# Mount $AGENT_DIR as /agent-config (NOT /app/config — that would overlay
# the Python config package and break imports like config.agent_identity).
if [ "$GATEWAY" = true ]; then
    # Gateway mode: no host port mapping. Agent connects UP to Gateway.
    GATEWAY_URL="${GATEWAY_URL:-ws://host.docker.internal:8001}"
    docker run -d \
        --name "$CONTAINER_NAME" \
        --add-host=host.docker.internal:host-gateway \
        -v "$AGENT_DIR/:/agent-config/" \
        -e "AGENT_ID=${AGENT_ID}" \
        -e "OPENROUTER_API_KEY=${API_KEY}" \
        -e "AGENT_CONFIG_DIR=/agent-config/" \
        -e "SHOPKEEPER_SERVER_TOKEN=${SERVER_TOKEN}" \
        -e "GATEWAY_URL=${GATEWAY_URL}" \
        -e "GATEWAY_AGENT_TOKEN=${GATEWAY_AGENT_TOKEN}" \
        --restart unless-stopped \
        --memory 512m \
        --cpus 0.5 \
        alive-engine:latest
    echo "  Container started (Gateway mode): $CONTAINER_NAME"
else
    # Legacy mode: host port mapping
    docker run -d \
        --name "$CONTAINER_NAME" \
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
    echo "  Container started: $CONTAINER_NAME"
fi

# Wait for health
if [ "$GATEWAY" = true ]; then
    # Gateway mode: wait for agent to register with Gateway
    GATEWAY_HTTP="${GATEWAY_HTTP_URL:-http://127.0.0.1:8000}"
    GATEWAY_ADMIN_TOKEN="${GATEWAY_ADMIN_TOKEN:-}"
    GW_REGISTERED=false
    echo -n "  Waiting for agent to register with Gateway"
    for i in $(seq 1 30); do
        HEALTH=$(curl -s -H "X-Gateway-Token: ${GATEWAY_ADMIN_TOKEN}" \
            "${GATEWAY_HTTP}/agents/${AGENT_ID}/health" 2>/dev/null || echo '{}')
        # Validate: must be valid JSON with a known healthy status field
        # (rejects auth errors, empty responses, and "unreachable")
        if echo "$HEALTH" | python3 -c "
import sys, json
d = json.load(sys.stdin)
st = d.get('status', '')
# Only accept real health statuses — reject 'unreachable', auth errors, etc.
sys.exit(0 if st and st not in ('unreachable',) and 'error' not in d else 1)
" 2>/dev/null; then
            echo ""
            echo "  Agent '$AGENT_ID' registered with Gateway"
            GW_REGISTERED=true
            break
        fi
        echo -n "."
        sleep 2
    done

    if [ "$GW_REGISTERED" = false ]; then
        echo ""
        echo "  WARNING: Agent did not register with Gateway after 60s."
        echo "     Check logs: docker logs $CONTAINER_NAME --tail 50"
        echo "     Gateway:    curl -H 'X-Gateway-Token: ...' ${GATEWAY_HTTP}/agents/${AGENT_ID}/health"
        exit 1
    fi
else
    echo -n "  Waiting for agent to start"
    for i in $(seq 1 30); do
        if curl -s "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
            echo ""
            echo "  Agent '$AGENT_ID' is healthy on port $PORT"
            break
        fi
        echo -n "."
        sleep 2
    done

    # Check if we timed out
    if ! curl -s "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
        echo ""
        echo "  Agent not responding after 60s. Check logs:"
        echo "     docker logs $CONTAINER_NAME --tail 50"
    fi

    # Update nginx routes (legacy mode only)
    if [ -f "$SCRIPT_DIR/nginx_regen.sh" ]; then
        echo "  Updating nginx routes..."
        bash "$SCRIPT_DIR/nginx_regen.sh"
    fi
fi

echo ""
echo "Agent '$AGENT_ID' created."
if [ "$GATEWAY" = true ]; then
    echo "  Mode:   Gateway (no host port)"
    echo "  Health: via Gateway /agents/${AGENT_ID}/health"
else
    echo "  Local:  http://127.0.0.1:${PORT}/api/state"
    echo "  Public: https://api.alive.kaikk.jp/${AGENT_ID}/state"
fi
echo "  Logs:   docker logs $CONTAINER_NAME -f"
echo "  Config: $AGENT_DIR/"
