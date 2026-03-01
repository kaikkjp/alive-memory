#!/usr/bin/env bash
# Deploy lounge to VPS from GitHub.
# Usage: ./scripts/deploy-lounge.sh
set -euo pipefail

VPS="shopkeeper"
REPO_DIR="/opt/alive/shopkeeper"
LOUNGE_DIR="$REPO_DIR/lounge"

echo "==> Pulling latest from GitHub..."
ssh "$VPS" "cd $REPO_DIR && git pull --ff-only"

echo "==> Installing dependencies..."
ssh "$VPS" "cd $LOUNGE_DIR && npm install --production=false 2>&1 | tail -3"

echo "==> Building..."
ssh "$VPS" "cd $LOUNGE_DIR && npm run build 2>&1 | tail -5"

echo "==> Restarting service..."
ssh "$VPS" "systemctl restart alive-lounge"

sleep 3

echo "==> Verifying..."
STATUS=$(ssh "$VPS" "systemctl is-active alive-lounge")
if [ "$STATUS" = "active" ]; then
  echo "✓ alive-lounge is running"
else
  echo "✗ alive-lounge failed to start"
  ssh "$VPS" "journalctl -u alive-lounge --no-pager -n 20"
  exit 1
fi
