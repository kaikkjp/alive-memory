#!/bin/bash
set -euo pipefail

DOMAIN="${1:?Usage: $0 <domain> <email>}"
EMAIL="${2:?Usage: $0 <domain> <email>}"

echo "Obtaining Let's Encrypt certificate for ${DOMAIN}..."

# Obtain cert via standalone certbot (port 80 must be free)
docker run --rm -p 80:80 \
    -v "$(pwd)/certbot-etc:/etc/letsencrypt" \
    certbot/certbot certonly --standalone \
    -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL"

# Create the certbot container (and its certs volume) without starting it
docker compose up --no-start certbot

# Copy certs into the Compose-managed volume via the certbot service
docker compose cp "certbot-etc/." certbot:/etc/letsencrypt/

# Clean up local copy and stop the helper container
docker compose stop certbot 2>/dev/null || true
rm -rf certbot-etc

echo ""
echo "Certificate obtained. Now:"
echo "  1. Edit deploy/nginx.conf — replace YOURDOMAIN with ${DOMAIN}"
echo "  2. Run: docker compose up -d"
