#!/bin/bash
# FULLY AUTOMATED SHOPKEEPER DEPLOYMENT
# Just run: bash DEPLOY-NOW.sh

set -e

VPS_IP="89.167.23.147"
DOMAIN="shopkeeper.tokyo"
REPO="TriMinhPham/shopkeeper"
API_KEY="${OPENROUTER_API_KEY:?Set OPENROUTER_API_KEY before running this script}"

echo "🚀 DEPLOYING SHOPKEEPER - FULLY AUTOMATED"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ──────────────────────────────────────────────
# STEP 1: Run non-interactive setup on VPS
# ──────────────────────────────────────────────
echo "📦 Step 1: Setting up VPS..."

ssh -o StrictHostKeyChecking=no root@${VPS_IP} bash <<ENDSSH
set -euo pipefail

DOMAIN="${DOMAIN}"
APP_DIR="/var/www/shopkeeper"
REPO_URL="https://github.com/${REPO}.git"
DEPLOY_USER="shopkeeper"

# 1. Install packages
echo "[1/9] Installing system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3.12 python3.12-venv python3.12-dev \
    nginx certbot python3-certbot-nginx \
    git curl ufw sqlite3 build-essential

# Node.js 20
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y -qq nodejs
fi

# 2. Create user
echo "[2/9] Creating \${DEPLOY_USER} user..."
if ! id -u "\${DEPLOY_USER}" &>/dev/null; then
    useradd --system --create-home --shell /bin/bash "\${DEPLOY_USER}"
fi

# 3. Generate deploy key (for GitHub)
echo "[3/9] Generating deploy key..."
DEPLOY_KEY="/home/\${DEPLOY_USER}/.ssh/id_ed25519"
mkdir -p "/home/\${DEPLOY_USER}/.ssh"
if [ ! -f "\${DEPLOY_KEY}" ]; then
    ssh-keygen -t ed25519 -f "\${DEPLOY_KEY}" -N "" -C "shopkeeper-deploy@\$(hostname)"
    chown -R "\${DEPLOY_USER}:\${DEPLOY_USER}" "/home/\${DEPLOY_USER}/.ssh"
    chmod 700 "/home/\${DEPLOY_USER}/.ssh"
    chmod 600 "\${DEPLOY_KEY}"
fi

# Print deploy key for GitHub
echo "──────────────────────────────────────"
echo "DEPLOY_KEY_PUBLIC:"
cat "\${DEPLOY_KEY}.pub"
echo "──────────────────────────────────────"

# Use HTTPS clone for now (will switch to SSH after deploy key is added)
echo "[4/9] Cloning repository via HTTPS..."
if [ ! -d "\${APP_DIR}/.git" ]; then
    git clone "\${REPO_URL}" "\${APP_DIR}"
    chown -R "\${DEPLOY_USER}:\${DEPLOY_USER}" "\${APP_DIR}"
fi
cd "\${APP_DIR}"

mkdir -p "\${APP_DIR}/data" "\${APP_DIR}/assets"
chown -R "\${DEPLOY_USER}:\${DEPLOY_USER}" "\${APP_DIR}"

# 5. Python environment
echo "[5/9] Setting up Python..."
if [ ! -d "\${APP_DIR}/.venv" ]; then
    sudo -u "\${DEPLOY_USER}" python3.12 -m venv "\${APP_DIR}/.venv"
fi
sudo -u "\${DEPLOY_USER}" "\${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "\${DEPLOY_USER}" "\${APP_DIR}/.venv/bin/pip" install --quiet -r "\${APP_DIR}/requirements.txt"

# 6. Build frontend
echo "[6/9] Building frontend..."
cd "\${APP_DIR}/window"
sudo -u "\${DEPLOY_USER}" npm ci --silent
sudo -u "\${DEPLOY_USER}" bash -c "
    cd \${APP_DIR}/window
    NEXT_PUBLIC_SITE_URL='https://\${DOMAIN}' npm run build
"

# 7. Environment file (non-interactive)
echo "[7/9] Creating .env..."
cat > "\${APP_DIR}/.env" <<ENVEOF
OPENROUTER_API_KEY=${API_KEY}
GEMINI_API_KEY=
SHOPKEEPER_WS_PORT=8765
SHOPKEEPER_HTTP_PORT=8080
ENVEOF
chown "\${DEPLOY_USER}:\${DEPLOY_USER}" "\${APP_DIR}/.env"
chmod 600 "\${APP_DIR}/.env"

# 8. Nginx + SSL (will skip SSL if DNS not ready)
echo "[8/9] Configuring Nginx..."
cp "\${APP_DIR}/nginx/shopkeeper.conf" /etc/nginx/sites-available/shopkeeper
ln -sf /etc/nginx/sites-available/shopkeeper /etc/nginx/sites-enabled/shopkeeper
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# Try to get SSL cert (will fail gracefully if DNS not ready)
echo "Attempting SSL certificate..."
if certbot --nginx -d "\${DOMAIN}" --non-interactive --agree-tos --register-unsafely-without-email --redirect 2>/dev/null; then
    echo "✓ SSL certificate obtained"
else
    echo "⚠️  SSL failed - DNS may not be ready. Run this later:"
    echo "   certbot --nginx -d \${DOMAIN} --non-interactive --agree-tos --register-unsafely-without-email --redirect"
fi

# 9. Systemd + firewall
echo "[9/9] Final setup..."
cp "\${APP_DIR}/deploy/shopkeeper.service" /etc/systemd/system/shopkeeper.service
systemctl daemon-reload
systemctl enable shopkeeper
systemctl start shopkeeper || systemctl restart shopkeeper

# Sudoers for deploy
cat > /etc/sudoers.d/shopkeeper <<SUDOERS
shopkeeper ALL=(ALL) NOPASSWD: /bin/systemctl restart shopkeeper, /bin/systemctl stop shopkeeper, /bin/systemctl start shopkeeper
SUDOERS
chmod 440 /etc/sudoers.d/shopkeeper

# CI SSH key for GitHub Actions
CI_KEY="/home/\${DEPLOY_USER}/.ssh/id_ed25519_ci"
if [ ! -f "\${CI_KEY}" ]; then
    ssh-keygen -t ed25519 -f "\${CI_KEY}" -N "" -C "shopkeeper-ci@\$(hostname)"
    chown "\${DEPLOY_USER}:\${DEPLOY_USER}" "\${CI_KEY}" "\${CI_KEY}.pub"
    chmod 600 "\${CI_KEY}"
    cat "\${CI_KEY}.pub" >> "/home/\${DEPLOY_USER}/.ssh/authorized_keys"
    chown "\${DEPLOY_USER}:\${DEPLOY_USER}" "/home/\${DEPLOY_USER}/.ssh/authorized_keys"
    chmod 600 "/home/\${DEPLOY_USER}/.ssh/authorized_keys"
fi

# Print CI private key
echo "──────────────────────────────────────"
echo "CI_SSH_PRIVATE_KEY:"
cat "\${CI_KEY}"
echo "──────────────────────────────────────"

# Print host fingerprint
echo "──────────────────────────────────────"
echo "VPS_HOST_FINGERPRINT:"
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub | awk '{print \$2}'
echo "──────────────────────────────────────"

# Add GitHub to known hosts
sudo -u "\${DEPLOY_USER}" bash -c 'ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null'

# Firewall
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# Backup cron
mkdir -p "/var/backups/shopkeeper"
chown "\${DEPLOY_USER}:\${DEPLOY_USER}" "/var/backups/shopkeeper"
cp "\${APP_DIR}/deploy/backup.sh" /etc/cron.daily/shopkeeper-backup
chmod +x /etc/cron.daily/shopkeeper-backup

echo ""
echo "✅ VPS setup complete!"
ENDSSH

# ──────────────────────────────────────────────
# STEP 2: Extract the keys from VPS output
# ──────────────────────────────────────────────
echo ""
echo "📋 Step 2: Extracting deploy keys and GitHub secrets..."
echo ""

# Get the deploy key
DEPLOY_KEY=\$(ssh root@${VPS_IP} 'cat /home/shopkeeper/.ssh/id_ed25519.pub')
echo "Deploy Key (add to GitHub):"
echo "\$DEPLOY_KEY"
echo ""

# Get CI SSH private key
CI_PRIVATE_KEY=\$(ssh root@${VPS_IP} 'cat /home/shopkeeper/.ssh/id_ed25519_ci')

# Get host fingerprint
HOST_FINGERPRINT=\$(ssh root@${VPS_IP} "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub | awk '{print \$2}'")

echo "──────────────────────────────────────"
echo "✅ DEPLOYMENT COMPLETE!"
echo "──────────────────────────────────────"
echo ""
echo "📝 TODO:"
echo ""
echo "1. Add DNS A record:"
echo "   Domain: ${DOMAIN}"
echo "   Type: A"
echo "   Value: ${VPS_IP}"
echo "   (Go to jp-domains.com)"
echo ""
echo "2. Add GitHub Deploy Key (read-only):"
echo "   https://github.com/${REPO}/settings/keys"
echo "   Title: shopkeeper-deploy"
echo "   Key: \$DEPLOY_KEY"
echo ""
echo "3. Add GitHub Actions Secrets:"
echo "   https://github.com/${REPO}/settings/secrets/actions"
echo ""
echo "   VPS_HOST = ${VPS_IP}"
echo "   VPS_SSH_KEY = (private key below)"
echo "   VPS_HOST_FINGERPRINT = \$HOST_FINGERPRINT"
echo ""
echo "CI Private Key (copy entire block):"
echo "\$CI_PRIVATE_KEY"
echo ""
echo "4. Test deployment:"
echo "   curl https://${DOMAIN}/api/health"
echo ""
echo "──────────────────────────────────────"
