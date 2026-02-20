#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Update environment variables on production server
#
# Usage: ./deploy/update-env.sh KEY=VALUE [KEY2=VALUE2 ...]
# Example: ./deploy/update-env.sh DASHBOARD_PASSWORD=heomirai
# ─────────────────────────────────────────────────────────────
set -euo pipefail

if [ $# -eq 0 ]; then
    echo "Usage: $0 KEY=VALUE [KEY2=VALUE2 ...]"
    echo "Example: $0 DASHBOARD_PASSWORD=heomirai"
    exit 1
fi

# Production server details
SSH_USER="shopkeeper"
SSH_HOST="shopkeeper.tokyo"
APP_DIR="/var/www/shopkeeper"
ENV_FILE="${APP_DIR}/.env"

echo "[update-env] Connecting to ${SSH_USER}@${SSH_HOST}..."

# Build the update commands
UPDATE_CMDS=""
for arg in "$@"; do
    if [[ ! "$arg" =~ ^[A-Z_]+=.+$ ]]; then
        echo "ERROR: Invalid format '$arg'. Use KEY=VALUE"
        exit 1
    fi

    KEY="${arg%%=*}"
    VALUE="${arg#*=}"

    echo "[update-env] Setting ${KEY}=***"

    # Check if key exists, update or append
    UPDATE_CMDS+="if grep -q '^${KEY}=' '${ENV_FILE}' 2>/dev/null; then "
    UPDATE_CMDS+="  sed -i 's|^${KEY}=.*|${KEY}=${VALUE}|' '${ENV_FILE}'; "
    UPDATE_CMDS+="else "
    UPDATE_CMDS+="  echo '${KEY}=${VALUE}' >> '${ENV_FILE}'; "
    UPDATE_CMDS+="fi; "
done

# Add restart command
UPDATE_CMDS+="sudo systemctl restart shopkeeper; "
UPDATE_CMDS+="sleep 2; "
UPDATE_CMDS+="sudo systemctl status shopkeeper --no-pager"

# Execute on remote server
ssh "${SSH_USER}@${SSH_HOST}" "bash -c '${UPDATE_CMDS}'"

echo "[update-env] Environment updated and service restarted"
echo "[update-env] Verify at: https://${SSH_HOST}/dashboard"
