#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Shopkeeper VPS Bootstrap — run once on a fresh Ubuntu 24.04
#
# Usage:  ssh root@YOUR_VPS_IP
#         curl -sL https://raw.githubusercontent.com/TriMinhPham/shopkeeper/main/deploy/setup.sh | bash
#         — or —
#         bash deploy/setup.sh
#
# Prerequisites:
#   - Ubuntu 24.04 LTS (Hetzner CX22 recommended)
#   - Root SSH access
#   - shopkeeper.tokyo DNS A record pointing to this server
# ─────────────────────────────────────────────────────────────
set -euo pipefail

DOMAIN="shopkeeper.tokyo"
APP_DIR="/var/www/shopkeeper"
BACKUP_DIR="/var/backups/shopkeeper"
REPO="git@github.com:TriMinhPham/shopkeeper.git"
DEPLOY_USER="shopkeeper"

echo "──────────────────────────────────────"
echo "  Shopkeeper VPS Setup"
echo "  Domain: ${DOMAIN}"
echo "──────────────────────────────────────"

# ─── Must be root ───
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Run as root."
    exit 1
fi

# ─── 1. System packages ───
echo "[1/9] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3.12 python3.12-venv python3.12-dev \
    nginx certbot python3-certbot-nginx \
    git curl ufw sqlite3 \
    build-essential

# Node.js 20 LTS (for building frontend)
if ! command -v node &>/dev/null; then
    echo "  Installing Node.js 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y -qq nodejs
fi

echo "  Python: $(python3.12 --version)"
echo "  Node:   $(node --version)"
echo "  npm:    $(npm --version)"

# ─── 2. Create shopkeeper user ───
echo "[2/9] Creating ${DEPLOY_USER} user..."
if ! id -u "${DEPLOY_USER}" &>/dev/null; then
    useradd --system --create-home --shell /bin/bash "${DEPLOY_USER}"
    echo "  Created user: ${DEPLOY_USER}"
else
    echo "  User ${DEPLOY_USER} already exists."
fi

# ─── 3. SSH deploy key (for private repo) ───
echo "[3/9] Setting up deploy key..."
DEPLOY_KEY="/home/${DEPLOY_USER}/.ssh/id_ed25519"
if [ ! -f "${DEPLOY_KEY}" ]; then
    mkdir -p "/home/${DEPLOY_USER}/.ssh"
    ssh-keygen -t ed25519 -f "${DEPLOY_KEY}" -N "" -C "shopkeeper-deploy@$(hostname)"
    chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"
    chmod 700 "/home/${DEPLOY_USER}/.ssh"
    chmod 600 "${DEPLOY_KEY}"

    echo ""
    echo "  ┌─────────────────────────────────────────────────────┐"
    echo "  │  DEPLOY KEY — Add this to GitHub Deploy Keys        │"
    echo "  │  Repo → Settings → Deploy Keys → Add (read-only)   │"
    echo "  └─────────────────────────────────────────────────────┘"
    echo ""
    cat "${DEPLOY_KEY}.pub"
    echo ""
    read -rp "  Press ENTER after adding the key to GitHub... "
else
    echo "  Deploy key already exists."
fi

# Add GitHub to known hosts
sudo -u "${DEPLOY_USER}" bash -c '
    ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null
    sort -u -o ~/.ssh/known_hosts ~/.ssh/known_hosts
'

# ─── 4. Clone repository ───
echo "[4/9] Cloning repository..."
if [ ! -d "${APP_DIR}/.git" ]; then
    sudo -u "${DEPLOY_USER}" git clone "${REPO}" "${APP_DIR}"
    echo "  Cloned to ${APP_DIR}"
else
    echo "  Repository already exists at ${APP_DIR}"
    cd "${APP_DIR}"
    sudo -u "${DEPLOY_USER}" git pull origin main
fi
cd "${APP_DIR}"

# Ensure data and assets dirs exist with correct ownership
mkdir -p "${APP_DIR}/data" "${APP_DIR}/assets"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}"

# ─── 5. Python venv + deps ───
echo "[5/9] Setting up Python environment..."
if [ ! -d "${APP_DIR}/.venv" ]; then
    sudo -u "${DEPLOY_USER}" python3.12 -m venv "${APP_DIR}/.venv"
fi
sudo -u "${DEPLOY_USER}" "${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "${DEPLOY_USER}" "${APP_DIR}/.venv/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"
echo "  Python deps installed."

# ─── 6. Build frontend ───
echo "[6/9] Building frontend..."
cd "${APP_DIR}/window"
sudo -u "${DEPLOY_USER}" npm ci --silent
sudo -u "${DEPLOY_USER}" bash -c "
    cd ${APP_DIR}/window
    NEXT_PUBLIC_API_URL='' \
    NEXT_PUBLIC_WS_URL='wss://${DOMAIN}/ws/' \
    NEXT_PUBLIC_ASSET_URL='/assets' \
    npm run build
"
echo "  Frontend built → window/out/"

# ─── 7. Environment file ───
echo "[7/9] Configuring environment..."
ENV_FILE="${APP_DIR}/.env"
if [ ! -f "${ENV_FILE}" ]; then
    echo ""
    read -rp "  Enter your ANTHROPIC_API_KEY: " API_KEY
    read -rp "  Enter your GEMINI_API_KEY (or press ENTER to skip): " GEMINI_KEY

    cat > "${ENV_FILE}" <<ENVEOF
ANTHROPIC_API_KEY=${API_KEY}
GEMINI_API_KEY=${GEMINI_KEY}
SHOPKEEPER_WS_PORT=8765
SHOPKEEPER_HTTP_PORT=8080
ENVEOF

    chown "${DEPLOY_USER}:${DEPLOY_USER}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    echo "  .env created (permissions: 600)"
else
    echo "  .env already exists."
fi

# ─── 8. Nginx + SSL ───
echo "[8/9] Configuring Nginx and SSL..."
cp "${APP_DIR}/nginx/shopkeeper.conf" /etc/nginx/sites-available/shopkeeper
ln -sf /etc/nginx/sites-available/shopkeeper /etc/nginx/sites-enabled/shopkeeper
rm -f /etc/nginx/sites-enabled/default

# Test nginx config
nginx -t

# Reload with HTTP-only first (needed for certbot)
systemctl reload nginx

# Get SSL cert
echo "  Requesting SSL certificate for ${DOMAIN}..."
certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --register-unsafely-without-email --redirect

echo "  SSL configured. Auto-renewal via certbot timer."

# ─── 9. Systemd + firewall + backup ───
echo "[9/9] Setting up systemd, firewall, and backups..."

# Systemd
cp "${APP_DIR}/deploy/shopkeeper.service" /etc/systemd/system/shopkeeper.service
systemctl daemon-reload
systemctl enable shopkeeper
systemctl start shopkeeper
echo "  Service started."

# Allow shopkeeper user to restart its own service (needed by deploy.sh)
cat > /etc/sudoers.d/shopkeeper <<SUDOERS
shopkeeper ALL=(ALL) NOPASSWD: /bin/systemctl restart shopkeeper, /bin/systemctl stop shopkeeper, /bin/systemctl start shopkeeper
SUDOERS
chmod 440 /etc/sudoers.d/shopkeeper
echo "  Sudoers configured for service management."

# Firewall
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
echo "  Firewall enabled (SSH + HTTP/HTTPS only)."

# Backup cron
mkdir -p "${BACKUP_DIR}"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${BACKUP_DIR}"
cp "${APP_DIR}/deploy/backup.sh" /etc/cron.daily/shopkeeper-backup
chmod +x /etc/cron.daily/shopkeeper-backup
echo "  Daily backup cron installed."

# ─── Done ───
echo ""
echo "══════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  Site:    https://${DOMAIN}"
echo "  Status:  systemctl status shopkeeper"
echo "  Logs:    journalctl -u shopkeeper -f"
echo "  Restart: systemctl restart shopkeeper"
echo ""
echo "  Next steps:"
echo "  1. Verify: curl https://${DOMAIN}/api/health"
echo "  2. Generate invite tokens:"
echo "     cd ${APP_DIR}"
echo "     sudo -u ${DEPLOY_USER} .venv/bin/python generate_token.py --name 'Visitor' --uses 5"
echo "  3. Set up GitHub Actions secrets:"
echo "     VPS_HOST = $(curl -s ifconfig.me)"
echo "     VPS_SSH_KEY = (SSH private key for the shopkeeper user)"
echo "══════════════════════════════════════"
