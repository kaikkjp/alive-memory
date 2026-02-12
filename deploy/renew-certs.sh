#!/bin/bash
# Renew TLS certificates and reload nginx.
# Add to crontab:
#   0 3 * * * /opt/shopkeeper/deploy/renew-certs.sh >> /var/log/shopkeeper-certbot.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."

docker compose exec certbot certbot renew --webroot -w /var/www/certbot --quiet
docker compose exec nginx nginx -s reload
