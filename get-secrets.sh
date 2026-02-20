#!/bin/bash
# Quick script to get GitHub secret values from VPS
VPS_IP="89.167.23.147"

echo "Getting values from VPS for GitHub secrets..."
echo ""

ssh -o StrictHostKeyChecking=no root@${VPS_IP} bash <<'ENDSSH'
echo "VPS_HOST:"
curl -s ifconfig.me
echo ""
echo ""
echo "VPS_HOST_FINGERPRINT:"
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub 2>/dev/null | awk '{print $2}' || echo "Not yet available"
echo ""
echo ""
echo "VPS_SSH_KEY (CI Private Key):"
cat /home/shopkeeper/.ssh/id_ed25519_ci 2>/dev/null || echo "Not yet generated - run setup first"
echo ""
ENDSSH
