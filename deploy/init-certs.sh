#!/bin/bash
set -euo pipefail

DOMAIN="${1:?Usage: $0 <domain> <email>}"
EMAIL="${2:?Usage: $0 <domain> <email>}"

echo "Obtaining Let's Encrypt certificate for ${DOMAIN}..."

docker run --rm -p 80:80 \
    -v "$(pwd)/certbot-etc:/etc/letsencrypt" \
    certbot/certbot certonly --standalone \
    -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL"

# Copy certs into the named volume
docker compose up -d --no-deps nginx 2>/dev/null || true
docker compose cp certbot-etc/. shopkeeper-certbot:/etc/letsencrypt/ 2>/dev/null || true

# Alternative: create the volume and populate it directly
docker volume create shopkeeper_certs 2>/dev/null || true
docker run --rm \
    -v "$(pwd)/certbot-etc:/src:ro" \
    -v "shopkeeper_certs:/dst" \
    alpine sh -c 'cp -rL /src/* /dst/'

rm -rf certbot-etc

echo ""
echo "Certificate obtained. Now:"
echo "  1. Edit deploy/nginx.conf — replace YOURDOMAIN with ${DOMAIN}"
echo "  2. Run: docker compose up -d"
