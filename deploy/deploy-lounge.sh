#!/bin/bash
# deploy-lounge.sh — Deploy the Private Lounge platform to VPS
# Run this ON the VPS (89.167.23.147)
#
# Prerequisites:
#   - Docker installed
#   - nginx installed
#   - Node.js 20+ installed (for lounge portal)
#   - Git access to the repo
#
# Usage:
#   scp deploy-lounge.sh user@89.167.23.147:~/
#   ssh user@89.167.23.147
#   chmod +x deploy-lounge.sh
#   ./deploy-lounge.sh

set -euo pipefail

LOUNGE_PORT=3100
DATA_DIR="/data/alive-agents"
REPO_DIR=""  # Set to your repo checkout path, e.g. /home/heo/shopkeeper

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# --- Preflight checks ---
log "Running preflight checks..."

if [ -z "$REPO_DIR" ]; then
    err "Set REPO_DIR in this script to your repo checkout path"
fi

if [ ! -d "$REPO_DIR" ]; then
    err "REPO_DIR=$REPO_DIR does not exist"
fi

command -v docker >/dev/null 2>&1 || err "Docker not installed"
command -v nginx >/dev/null 2>&1  || err "nginx not installed"
command -v node >/dev/null 2>&1   || err "Node.js not installed"
command -v npm >/dev/null 2>&1    || err "npm not installed"

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 20 ]; then
    err "Node.js 20+ required, got $(node -v)"
fi

log "All preflight checks passed."

# --- Step 1: Create data directories ---
log "Creating data directories..."
sudo mkdir -p "$DATA_DIR"
sudo chown "$(whoami):$(whoami)" "$DATA_DIR"

# --- Step 2: Build agent Docker image ---
log "Building agent Docker image..."
cd "$REPO_DIR"

if [ ! -f "deploy/Dockerfile.agent" ]; then
    warn "deploy/Dockerfile.agent not found, using default Dockerfile"
    DOCKERFILE="Dockerfile"
else
    DOCKERFILE="deploy/Dockerfile.agent"
fi

docker build -f "$DOCKERFILE" -t alive-engine:latest .
log "Agent image built: alive-engine:latest"

# --- Step 3: Install + build lounge portal ---
log "Building lounge portal..."
cd "$REPO_DIR/lounge"

if [ ! -f "package.json" ]; then
    err "lounge/package.json not found. Has TASK-095 Phase 5+6 been built?"
fi

npm ci
npm run build
log "Lounge portal built."

# --- Step 4: Set up lounge systemd service ---
log "Creating lounge systemd service..."
sudo tee /etc/systemd/system/alive-lounge.service > /dev/null <<EOF
[Unit]
Description=ALIVE Private Lounge Portal
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$REPO_DIR/lounge
Environment=NODE_ENV=production
Environment=PORT=$LOUNGE_PORT
Environment=DATA_DIR=$DATA_DIR
ExecStart=$(which npm) start
Restart=unless-stopped
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable alive-lounge
sudo systemctl restart alive-lounge
log "Lounge portal running on port $LOUNGE_PORT"

# --- Step 5: Configure nginx ---
log "Configuring nginx..."

# Copy nginx config
sudo cp "$REPO_DIR/deploy/nginx-alive-lounge.conf" /etc/nginx/sites-available/alive-lounge

# Enable site
sudo ln -sf /etc/nginx/sites-available/alive-lounge /etc/nginx/sites-enabled/alive-lounge

# Test nginx config
sudo nginx -t || err "nginx config test failed"

# Reload
sudo systemctl reload nginx
log "nginx configured and reloaded."

# --- Step 6: Verify ---
log "Verifying deployment..."

sleep 3

# Check lounge portal
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$LOUNGE_PORT/ 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "307" ]; then
    log "✅ Lounge portal responding (HTTP $HTTP_CODE)"
else
    warn "⚠️  Lounge portal returned HTTP $HTTP_CODE — check: sudo journalctl -u alive-lounge -n 50"
fi

# Check nginx
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: alive.kaikk.jp" http://127.0.0.1/ 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "307" ]; then
    log "✅ nginx routing alive.kaikk.jp (HTTP $HTTP_CODE)"
else
    warn "⚠️  nginx returned HTTP $HTTP_CODE for alive.kaikk.jp"
fi

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: api.alive.kaikk.jp" http://127.0.0.1/ 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "404" ]; then
    log "✅ nginx routing api.alive.kaikk.jp (HTTP 404 = correct, no agents yet)"
else
    warn "⚠️  nginx returned HTTP $HTTP_CODE for api.alive.kaikk.jp (expected 404)"
fi

# --- Done ---
echo ""
log "========================================="
log "  Private Lounge deployed!"
log "========================================="
log ""
log "  Portal:  https://alive.kaikk.jp"
log "  API:     https://api.alive.kaikk.jp"
log "  Data:    $DATA_DIR"
log ""
log "  Next steps:"
log "  1. Generate a manager token:"
log "     cd $REPO_DIR/lounge && npx ts-node scripts/generate-manager-token.ts"
log "  2. Log in at https://alive.kaikk.jp"
log "  3. Create your first agent"
log ""
log "  Useful commands:"
log "    sudo journalctl -u alive-lounge -f        # portal logs"
log "    docker ps --filter name=alive-agent        # running agents"
log "    sudo nginx -t && sudo systemctl reload nginx  # after agent changes"
log ""
