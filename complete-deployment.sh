#!/bin/bash
# Complete Shopkeeper Deployment Automation
# This script will guide you through the entire deployment

set -e

VPS_IP="89.167.23.147"
DOMAIN="shopkeeper.tokyo"
SSH_KEY="$HOME/.ssh/id_ed25519"

echo "========================================="
echo "Shopkeeper Complete Deployment"
echo "========================================="
echo ""
echo "VPS IP: $VPS_IP"
echo "Domain: $DOMAIN"
echo ""

# Step 1: Test SSH connection
echo "Step 1: Testing SSH connection to VPS..."
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no root@$VPS_IP "echo 'SSH connection successful'" 2>/dev/null; then
    echo "✓ SSH connection working"
else
    echo "✗ SSH connection failed"
    echo ""
    echo "Please run this command in your terminal to connect:"
    echo "ssh root@$VPS_IP"
    echo ""
    echo "Then run these commands on the VPS:"
    echo "apt update && apt install -y git"
    echo "git clone https://github.com/TriMinhPham/shopkeeper.git /tmp/shopkeeper-setup"
    echo "bash /tmp/shopkeeper-setup/deploy/setup.sh"
    echo ""
    exit 1
fi

# Step 2: Run setup on VPS
echo ""
echo "Step 2: Running setup script on VPS..."
ssh root@$VPS_IP 'bash -s' << 'ENDSSH'
    set -e
    apt update -qq
    apt install -y git
    git clone https://github.com/TriMinhPham/shopkeeper.git /tmp/shopkeeper-setup
    cd /tmp/shopkeeper-setup
    bash deploy/setup.sh
ENDSSH

echo ""
echo "========================================="
echo "Deployment complete!"
echo ""
echo "Next steps:"
echo "1. Add DNS A record: $DOMAIN → $VPS_IP"
echo "2. Add GitHub secrets (check VPS output above)"
echo "3. Test: curl https://$DOMAIN/api/health"
echo "========================================="
