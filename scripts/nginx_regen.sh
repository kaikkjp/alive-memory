#!/bin/bash
# nginx_regen.sh — Regenerate nginx agent routes from running containers
# Called by create_agent.sh and destroy_agent.sh
#
# Reads all alive-agent-* containers and builds location blocks
# for api.alive.kaikk.jp

set -euo pipefail

NGINX_CONF="/etc/nginx/sites-available/alive-lounge"
MARKER_BEGIN="# --- BEGIN AGENT ROUTES ---"
MARKER_END="# --- END AGENT ROUTES ---"

if [ ! -f "$NGINX_CONF" ]; then
    echo "ERROR: $NGINX_CONF not found"
    exit 1
fi

# Build route block from running containers
ROUTES=""
while IFS= read -r line; do
    CONTAINER_NAME=$(echo "$line" | awk '{print $1}')
    AGENT_ID=${CONTAINER_NAME#alive-agent-}
    
    # Get the host port mapped to container port 8080
    PORT=$(docker port "$CONTAINER_NAME" 8080 2>/dev/null | head -1 | cut -d: -f2)
    
    if [ -n "$PORT" ]; then
        ROUTES+="    location /${AGENT_ID}/ {\n"
        ROUTES+="        proxy_pass http://127.0.0.1:${PORT}/;\n"
        ROUTES+="        proxy_http_version 1.1;\n"
        ROUTES+="        proxy_set_header Upgrade \$http_upgrade;\n"
        ROUTES+="        proxy_set_header Connection \"upgrade\";\n"
        ROUTES+="        proxy_set_header Host \$host;\n"
        ROUTES+="        proxy_set_header X-Real-IP \$remote_addr;\n"
        ROUTES+="        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;\n"
        ROUTES+="        proxy_read_timeout 60s;\n"
        ROUTES+="    }\n"
    fi
done < <(docker ps --filter "name=alive-agent-" --format "{{.Names}}")

# Replace between markers in nginx conf
# Use temp file to avoid sed -i portability issues
TMPFILE=$(mktemp)
awk -v routes="$ROUTES" -v begin="$MARKER_BEGIN" -v end="$MARKER_END" '
    $0 ~ begin { print; printf "%s", routes; skip=1; next }
    $0 ~ end   { skip=0 }
    !skip       { print }
' "$NGINX_CONF" > "$TMPFILE"

sudo cp "$TMPFILE" "$NGINX_CONF"
rm "$TMPFILE"

# Test and reload
sudo nginx -t || { echo "ERROR: nginx config test failed"; exit 1; }
sudo systemctl reload nginx

AGENT_COUNT=$(docker ps --filter "name=alive-agent-" --format "{{.Names}}" | wc -l)
echo "nginx updated: $AGENT_COUNT agent(s) routed"
