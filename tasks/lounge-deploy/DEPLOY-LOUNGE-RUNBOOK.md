# Private Lounge — Deployment Runbook

## Architecture

```
/opt/alive/shopkeeper/          ← git clone (deploy key: read-only)
  lounge/                       ← Next.js app, systemd service alive-lounge
    data/lounge.db              ← persistent DB (agent registrations, manager tokens)
  engine/                       ← Python engine (used by agent Docker containers)

/data/alive-agents/<id>/        ← per-agent config + data (bind-mounted into containers)
```

Engine (Shopkeeper + agents) = Docker containers.
Lounge = systemd service running Next.js on port 3100.
These are separate concerns — lounge restarts don't affect running agents.

---

## Deploying Lounge Changes

### Standard deploy (from local machine)

```bash
# 1. Push your changes to GitHub
git push origin main

# 2. Deploy
./scripts/deploy-lounge.sh
```

The script does: `git pull` → `npm install` → `npm run build` → `systemctl restart alive-lounge` → verify.

### Manual deploy (SSH)

```bash
ssh shopkeeper
cd /opt/alive/shopkeeper && git pull --ff-only
cd lounge && npm install && npm run build
sudo systemctl restart alive-lounge
sudo systemctl status alive-lounge
```

---

## Prerequisites on VPS (89.167.23.147)

```bash
docker --version          # Docker 20+
nginx -v                  # nginx
node -v                   # Node.js 20+
```

---

## First-Time Setup (already done)

These steps were completed on 2026-03-01. Documented for reference.

1. Generated SSH deploy key on VPS: `~/.ssh/id_ed25519_github`
2. Added as deploy key to `TriMinhPham/shopkeeper` on GitHub (read-only)
3. Cloned repo to `/opt/alive/shopkeeper/`
4. Restored `lounge/data/lounge.db` from previous rsync'd install
5. Updated systemd `WorkingDirectory` to `/opt/alive/shopkeeper/lounge`
6. Old rsync'd lounge archived to `/opt/alive/lounge.bak/`

---

## Manager Login

```bash
# Generate a manager token (on VPS):
cd /opt/alive/shopkeeper/lounge
npx ts-node scripts/generate-manager-token.ts
# Outputs: token_xxxxxxxx
```

Log in at https://alive.kaikk.jp with this token.

The dashboard is publicly accessible without login — all agents and their vitals are visible. Login is only required for management actions (start/stop/create/delete agents).

---

## Agent Management

```bash
# Create agent (via lounge API or scripts)
./scripts/create_agent.sh <name> <port> <openrouter-key>

# List agents
./scripts/list_agents.sh

# Destroy agent
./scripts/destroy_agent.sh <name>          # keeps data
./scripts/destroy_agent.sh <name> --purge  # deletes everything
```

---

## Troubleshooting

```bash
# Lounge logs
sudo journalctl -u alive-lounge -f

# Agent container logs
docker logs alive-agent-<name> -f

# nginx logs
sudo tail -f /var/log/nginx/error.log

# Restart lounge
sudo systemctl restart alive-lounge

# Restart agent container
docker restart alive-agent-<name>

# Check lounge DB
sqlite3 /opt/alive/shopkeeper/lounge/data/lounge.db ".tables"
```

---

## Cloudflare Notes

- SSL mode: "Flexible" works out of the box (Cloudflare → VPS on port 80)
- For "Full" mode: add Cloudflare origin cert to nginx (recommended for production)
- If you see "Error 522": VPS firewall or nginx not running
- If you see "Error 524": agent took >100s to respond (Cloudflare timeout)

---

## Important Warnings

- **Never delete `lounge/data/lounge.db`** — wipes all agent registrations and manager tokens
- **Never `git clean -f` in the lounge dir on VPS** — would delete the data dir
- **Deploy key is read-only** — you cannot push from VPS, only pull
- **`lounge/data/` is gitignored** — it only exists on the VPS, not in the repo
