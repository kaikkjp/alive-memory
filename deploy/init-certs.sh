#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Obtain initial Let's Encrypt TLS certificate for the Shopkeeper.
#
# Usage:  bash deploy/init-certs.sh yourdomain.com you@email.com
#
# Prerequisites:
#   - Docker and Docker Compose installed
#   - Port 80 open and reachable from the internet
#   - DNS A record pointing to this server
#   - docker compose build already completed
#
# This script:
#   1. Starts nginx with HTTP-only config (for ACME challenge)
#   2. Runs certbot to obtain the certificate
#   3. Patches nginx.conf with your domain
#   4. Restarts nginx with full TLS config
# ─────────────────────────────────────────────────────────────
set -euo pipefail

DOMAIN="${1:?Usage: $0 <domain> <email>}"
EMAIL="${2:?Usage: $0 <domain> <email>}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_DIR}"

echo "[init-certs] Obtaining certificate for ${DOMAIN}..."

# ── Step 1: Start nginx with HTTP-only config ───
echo "[init-certs] Starting nginx (HTTP only)..."
cp deploy/nginx-http-only.conf deploy/nginx-active.conf

# Temporarily swap nginx config mount
docker compose -f docker-compose.yml run -d --rm \
    --name shopkeeper-nginx-init \
    -p 80:80 \
    -v "${PROJECT_DIR}/deploy/nginx-active.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v certbot-webroot:/var/www/certbot \
    nginx:1.27-alpine

# Give nginx a moment to start
sleep 2

# ── Step 2: Run certbot ───
echo "[init-certs] Running certbot..."
docker run --rm \
    -v shopkeeper_certs:/etc/letsencrypt \
    -v shopkeeper_certbot-webroot:/var/www/certbot \
    certbot/certbot certonly \
    --webroot -w /var/www/certbot \
    -d "${DOMAIN}" \
    --non-interactive --agree-tos -m "${EMAIL}"

# ── Step 3: Stop temporary nginx ───
echo "[init-certs] Stopping temporary nginx..."
docker stop shopkeeper-nginx-init 2>/dev/null || true
rm -f deploy/nginx-active.conf

# ── Step 4: Patch domain into nginx.conf ───
echo "[init-certs] Configuring nginx for ${DOMAIN}..."
# Escape dots in domain for sed safety (e.g., shopkeeper.tokyo → shopkeeper\.tokyo in regex)
ESCAPED_DOMAIN=$(printf '%s\n' "${DOMAIN}" | sed 's/[&/\]/\\&/g')
sed -i.bak "s|DOMAIN|${ESCAPED_DOMAIN}|g" deploy/nginx.conf
# Also set server_name for the HTTPS block
sed -i "s|server_name _;|server_name ${ESCAPED_DOMAIN};|" deploy/nginx.conf
rm -f deploy/nginx.conf.bak

echo ""
echo "[init-certs] Certificate obtained for ${DOMAIN}"
echo "[init-certs] nginx.conf updated with domain."
echo ""
echo "Next steps:"
echo "  docker compose up -d"
echo ""
echo "Add cert renewal to crontab:"
echo "  sudo crontab -e"
echo "  0 3 * * * cd ${PROJECT_DIR} && bash deploy/renew-certs.sh >> /var/log/shopkeeper-certbot.log 2>&1"
