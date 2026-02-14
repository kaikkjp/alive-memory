#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Renew TLS certificates and reload nginx.
#
# Add to crontab:
#   0 3 * * * cd /path/to/shopkeeper && bash deploy/renew-certs.sh >> /var/log/shopkeeper-certbot.log 2>&1
# ─────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")/.."

docker compose exec -T certbot certbot renew --webroot -w /var/www/certbot --quiet
docker compose exec -T nginx nginx -s reload

echo "[renew-certs] Renewal check completed at $(date -Iseconds)"
