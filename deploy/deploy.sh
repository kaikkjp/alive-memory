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

# ─── Activate venv (so python3/pip resolve to .venv) ───
source .venv/bin/activate

# ─── Python deps ───
echo "[deploy] Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# ─── Prepare frontend assets (source PNGs → window/public/assets/) ───
echo "[deploy] Preparing frontend assets..."
pip install --quiet Pillow
bash scripts/prepare_assets.sh

# ─── Stop service to free RAM for build ───
echo "[deploy] Stopping shopkeeper service (freeing RAM for build)..."
sudo systemctl stop shopkeeper

# Always restart the service, even if the build fails
trap 'echo "[deploy] Ensuring shopkeeper service is running..."; sudo systemctl start shopkeeper' EXIT

# ─── Build frontend ───
echo "[deploy] Building frontend..."
cd demo/window
rm -rf node_modules .next out
npm ci --silent
NEXT_PUBLIC_SITE_URL="https://${DOMAIN}" \
NODE_OPTIONS="--max-old-space-size=1536" \
npm run build
cd ..

# ─── Nginx config ───
# NOT auto-synced. Certbot manages SSL directives in the live config,
# so overwriting it breaks HTTPS. To update nginx config manually:
#   sudo cp /var/www/shopkeeper/demo/nginx/shopkeeper.conf /etc/nginx/sites-available/shopkeeper
#   sudo certbot --nginx -d shopkeeper.tokyo --non-interactive --agree-tos --register-unsafely-without-email --redirect
#   sudo nginx -t && sudo systemctl reload nginx

# ─── Restart service ───
# (trap above ensures this runs even on build failure, but we also start explicitly)
echo "[deploy] Starting shopkeeper service..."
sudo systemctl start shopkeeper
trap - EXIT

# ─── Health check (initial grace period + retries) ───
echo "[deploy] Waiting for service to start..."
HEALTH_URL="http://127.0.0.1:8080/api/health"
MAX_RETRIES=10
RETRY_INTERVAL=3
INITIAL_WAIT=10

echo "[deploy] Initial grace period (${INITIAL_WAIT}s for migrations + startup)..."
sleep ${INITIAL_WAIT}

for i in $(seq 1 ${MAX_RETRIES}); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${HEALTH_URL}" || echo "000")
    if [ "${HTTP_CODE}" = "200" ]; then
        echo "[deploy] Health check passed (HTTP ${HTTP_CODE}) on attempt ${i}"
        echo "[deploy] Deployment complete at $(date -Iseconds)"
        exit 0
    fi
    echo "[deploy] Health check attempt ${i}/${MAX_RETRIES}: HTTP ${HTTP_CODE}"
    sleep ${RETRY_INTERVAL}
done

echo "[deploy] ERROR: Health check failed after ${INITIAL_WAIT}s + $((MAX_RETRIES * RETRY_INTERVAL))s"
echo "[deploy] Check logs: journalctl -u shopkeeper -n 50"
exit 1
