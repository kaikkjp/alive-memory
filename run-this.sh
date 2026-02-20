#!/bin/bash
# ONE COMMAND TO RULE THEM ALL
# Save this and run: bash run-this.sh

set -e

VPS_IP="89.167.23.147"
REPO="TriMinhPham/shopkeeper"
DOMAIN="shopkeeper.tokyo"

echo "🚀 Deploying Shopkeeper to VPS..."
echo ""

# Copy SSH key to VPS if needed
echo "📋 Setting up SSH access..."
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@$VPS_IP 2>/dev/null || true

# Run the full setup on VPS
echo "⚙️  Running setup on VPS (this will take 2-3 minutes)..."
ssh -o StrictHostKeyChecking=no root@$VPS_IP bash << 'ENDSSH'
set -e
export DEBIAN_FRONTEND=noninteractive

echo "Installing git..."
apt-get update -qq
apt-get install -y git curl

echo "Cloning repository..."
rm -rf /tmp/shopkeeper-setup
git clone https://github.com/TriMinhPham/shopkeeper.git /tmp/shopkeeper-setup

echo "Running setup script..."
cd /tmp/shopkeeper-setup
bash deploy/setup.sh
ENDSSH

echo ""
echo "✅ Done! Your server is running at https://$DOMAIN"
echo ""
echo "📝 NEXT STEPS:"
echo "1. Add DNS A record: $DOMAIN → $VPS_IP (at jp-domains.com)"
echo "2. Add GitHub secrets (values are printed above)"
echo "3. Test: curl https://$DOMAIN/api/health"
echo ""
