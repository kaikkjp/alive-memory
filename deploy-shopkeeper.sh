#!/bin/bash
# Shopkeeper VPS Setup Script
# Run this on your VPS: bash <(curl -s https://raw.githubusercontent.com/TriMinhPham/shopkeeper/main/deploy/setup.sh)

set -e

VPS_IP="89.167.23.147"

echo "========================================="
echo "Shopkeeper VPS Setup"
echo "VPS IP: $VPS_IP"
echo "========================================="
echo ""

# Install git
echo "Installing git..."
apt update -qq
apt install -y git

# Clone repository
echo "Cloning shopkeeper repository..."
git clone https://github.com/TriMinhPham/shopkeeper.git /tmp/shopkeeper-setup

# Run setup script
echo "Running setup script..."
cd /tmp/shopkeeper-setup
bash deploy/setup.sh

echo ""
echo "========================================="
echo "Setup complete!"
echo "========================================="
