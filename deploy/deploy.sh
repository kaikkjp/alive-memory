#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Shopkeeper CD Deploy — called by GitHub Actions on push to main
#
# Usage:  sudo -u shopkeeper bash /var/www/shopkeeper/deploy/deploy.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/var/www/shopkeeper"
DOMAIN="shopkeeper.tokyo"

cd "${APP_DIR}"

echo "[deploy] Starting deployment at $(date -Iseconds)"

# ─── Pull latest code ───
echo "[deploy] Pulling latest code..."
git fetch origin main
git reset --hard origin/main

# ─── Python deps ───
echo "[deploy] Installing Python dependencies..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

# ─── Build frontend ───
echo "[deploy] Building frontend..."
cd window
npm ci --silent
NEXT_PUBLIC_API_URL='' \
NEXT_PUBLIC_WS_URL="wss://${DOMAIN}/ws/" \
NEXT_PUBLIC_ASSET_URL='/assets' \
npm run build
cd ..

# ─── Restart service ───
echo "[deploy] Restarting shopkeeper service..."
sudo systemctl restart shopkeeper

# ─── Health check ───
echo "[deploy] Waiting for service to start..."
sleep 3

HEALTH_URL="http://127.0.0.1:8080/api/health"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${HEALTH_URL}" || echo "000")

if [ "${HTTP_CODE}" = "200" ]; then
    echo "[deploy] Health check passed (HTTP ${HTTP_CODE})"
else
    echo "[deploy] WARNING: Health check returned HTTP ${HTTP_CODE}"
    echo "[deploy] Check logs: journalctl -u shopkeeper -n 50"
    exit 1
fi

echo "[deploy] Deployment complete at $(date -Iseconds)"
