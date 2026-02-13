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
NEXT_PUBLIC_SITE_URL="https://${DOMAIN}" \
npm run build
cd ..

# ─── Restart service ───
echo "[deploy] Restarting shopkeeper service..."
sudo systemctl restart shopkeeper

# ─── Health check (retry up to 5 times) ───
echo "[deploy] Waiting for service to start..."
HEALTH_URL="http://127.0.0.1:8080/api/health"
MAX_RETRIES=5
for i in $(seq 1 ${MAX_RETRIES}); do
    sleep 3
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${HEALTH_URL}" || echo "000")
    if [ "${HTTP_CODE}" = "200" ]; then
        echo "[deploy] Health check passed (HTTP ${HTTP_CODE}) on attempt ${i}"
        echo "[deploy] Deployment complete at $(date -Iseconds)"
        exit 0
    fi
    echo "[deploy] Health check attempt ${i}/${MAX_RETRIES}: HTTP ${HTTP_CODE}"
done

echo "[deploy] ERROR: Health check failed after ${MAX_RETRIES} attempts"
echo "[deploy] Check logs: journalctl -u shopkeeper -n 50"
exit 1
