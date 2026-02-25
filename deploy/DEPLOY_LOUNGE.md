# Deploying alive.kaikk.jp

Quick-start guide for the multi-agent platform.

## Prerequisites

- VPS with Docker installed
- Domain `alive.kaikk.jp` pointing to VPS IP
- Node.js 18+ on VPS (for portal)
- Python 3.12+ in Docker image

## 1. Build the agent image

```bash
docker build -f deploy/Dockerfile.agent -t alive-engine:latest .
```

## 2. Set up the portal

```bash
cd lounge
npm install

# Set environment variables
export LOUNGE_JWT_SECRET=$(openssl rand -hex 32)
export AGENTS_ROOT=/data/agents

# Create the first manager
npx tsx scripts/create-manager.ts "Your Name"
# Save the token printed — it's the login credential

# Build and start
npm run build
npm start  # runs on port 3000
```

## 3. Create an agent

```bash
# From the project root
./scripts/create_agent.sh my-agent 9001 sk-first-key
```

Or use the dashboard UI at `alive.kaikk.jp/dashboard` after logging in.

## 4. Set up nginx

```bash
# Generate agent proxy routes
./scripts/nginx_regen.sh

# Install the config
cp deploy/nginx-lounge.conf /etc/nginx/sites-available/alive.kaikk.jp
ln -sf /etc/nginx/sites-available/alive.kaikk.jp /etc/nginx/sites-enabled/

# TLS
certbot --nginx -d alive.kaikk.jp -d api.alive.kaikk.jp

nginx -t && systemctl reload nginx
```

## 5. Verify

```bash
# Portal
curl https://alive.kaikk.jp     # landing page

# Agent health
curl http://localhost:9001/api/health

# Public API (with key)
curl -H "Authorization: Bearer sk-first-key" \
     http://localhost:9001/api/public-state
```

## Agent lifecycle

```bash
./scripts/create_agent.sh <id> <port> <api-key>   # create
./scripts/destroy_agent.sh <id>                     # stop + remove
./scripts/destroy_agent.sh <id> --purge             # also delete data
./scripts/list_agents.sh                            # list all
./scripts/nginx_regen.sh                            # update proxy
```

## Directory structure per agent

```
/data/agents/<id>/
  identity.yaml       # character definition
  alive_config.yaml   # behavior config (optional)
  api_keys.json       # API keys for external access
  db/<id>.db           # SQLite database
  memory/              # episodic memory files
```

## Ports

| Service | Port | Notes |
|---------|------|-------|
| Portal (Next.js) | 3000 | Behind nginx |
| Agents | 9001+ | Auto-assigned, one per agent |
| nginx | 80/443 | TLS termination |

## Environment variables

### Portal (`lounge/`)
| Variable | Required | Description |
|----------|----------|-------------|
| `LOUNGE_JWT_SECRET` | Yes | Random 32+ byte hex for JWT signing |
| `AGENTS_ROOT` | No | Agent data root (default: `/data/agents`) |

### Agent containers
| Variable | Required | Description |
|----------|----------|-------------|
| `AGENT_ID` | Yes | Set by create_agent.sh |
| `AGENT_CONFIG_DIR` | Yes | Set by create_agent.sh |
| `OPENROUTER_API_KEY` | Yes | Provided in .env file per agent |
