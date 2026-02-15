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

# ─── Sync nginx config (if changed) ───
# Compare repo config against live config MINUS certbot-managed lines,
# so we only re-deploy when our own config actually changed.
echo "[deploy] Checking nginx config..."
LIVE_STRIPPED=$(grep -v '# managed by Certbot' /etc/nginx/sites-available/shopkeeper 2>/dev/null | grep -v 'managed by Certbot' || true)
REPO_STRIPPED=$(cat "${APP_DIR}/nginx/shopkeeper.conf")
if [ "$REPO_STRIPPED" != "$LIVE_STRIPPED" ]; then
    sudo cp "${APP_DIR}/nginx/shopkeeper.conf" /etc/nginx/sites-available/shopkeeper
    # Re-apply SSL cert (certbot adds listen 443, ssl_certificate directives)
    sudo certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --register-unsafely-without-email --redirect 2>/dev/null || true
    sudo nginx -t && sudo systemctl reload nginx
    echo "[deploy] Nginx config updated, SSL re-applied, nginx reloaded"
else
    echo "[deploy] Nginx config unchanged, skipping"
fi

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
