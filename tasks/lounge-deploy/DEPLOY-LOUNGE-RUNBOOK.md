# Private Lounge — Deployment Runbook

## Prerequisites on VPS (89.167.23.147)

```bash
# Check these are installed:
docker --version          # Docker 20+
nginx -v                  # nginx
node -v                   # Node.js 20+
```

If any missing, install first.

---

## Step 1: Copy deploy files to VPS

From your local machine, copy these files into the repo on VPS:

```
deploy/nginx-alive-lounge.conf    → repo/deploy/
deploy/deploy-lounge.sh           → repo/deploy/
scripts/create_agent.sh           → repo/scripts/
scripts/destroy_agent.sh          → repo/scripts/
scripts/list_agents.sh            → repo/scripts/
scripts/nginx_regen.sh            → repo/scripts/
```

Make scripts executable:
```bash
chmod +x deploy/deploy-lounge.sh scripts/*.sh
```

---

## Step 2: Set REPO_DIR and run deploy

```bash
# Edit the script — set REPO_DIR to your repo path
vim deploy/deploy-lounge.sh
# Change: REPO_DIR="" → REPO_DIR="/home/heo/shopkeeper" (or wherever)

# Run it
./deploy/deploy-lounge.sh
```

This will:
1. Create `/data/alive-agents/` directory
2. Build `alive-engine:latest` Docker image
3. Build the lounge Next.js app
4. Create + start systemd service for lounge portal (port 3100)
5. Install nginx config for both subdomains
6. Verify everything responds

---

## Step 3: Verify externally

```bash
# From your local machine:
curl -I https://alive.kaikk.jp          # Should get 200 (login page)
curl -I https://api.alive.kaikk.jp      # Should get 404 (no agents yet)
```

If Cloudflare returns 522 (connection refused): nginx isn't listening on port 80, or the VPS firewall blocks it.

---

## Step 4: Generate manager token

```bash
# On VPS:
cd /path/to/repo/lounge
npx ts-node scripts/generate-manager-token.ts
# Outputs: token_xxxxxxxx
```

Log in at https://alive.kaikk.jp with this token.

---

## Step 5: Create first agent (manual test)

```bash
# On VPS:
./scripts/create_agent.sh test-hina 9001 sk-or-v1-YOUR-OPENROUTER-KEY

# Verify:
curl http://127.0.0.1:9001/api/state
curl https://api.alive.kaikk.jp/test-hina/state
```

---

## Step 6: Test Private Lounge

1. Go to https://alive.kaikk.jp
2. Login with your manager token
3. Click your agent → Lounge
4. Send a message
5. Verify response comes back

---

## Troubleshooting

```bash
# Portal logs
sudo journalctl -u alive-lounge -f

# Agent logs
docker logs alive-agent-test-hina -f

# nginx logs
sudo tail -f /var/log/nginx/error.log

# List all agents
./scripts/list_agents.sh

# Restart portal
sudo systemctl restart alive-lounge

# Restart agent
docker restart alive-agent-test-hina

# Destroy agent
./scripts/destroy_agent.sh test-hina          # keeps data
./scripts/destroy_agent.sh test-hina --purge  # deletes everything
```

---

## Cloudflare Notes

- SSL mode: "Flexible" works out of the box (Cloudflare → VPS on port 80)
- For "Full" mode: add Cloudflare origin cert to nginx (recommended for production)
- The yellow warning on `api.alive` DNS record clears once nginx responds
- If you see "Error 522": VPS firewall or nginx not running
- If you see "Error 524": agent took >100s to respond (Cloudflare timeout)
