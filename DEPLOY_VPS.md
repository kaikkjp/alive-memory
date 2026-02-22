# VPS Deployment

## Docker Compose (recommended)

Uses Docker Compose with nginx for TLS termination, WebSocket proxying, and static frontend serving.

### Prerequisites

- Ubuntu 24.04 LTS VPS (Hetzner CX22 or similar)
- Docker and Docker Compose v2 installed
- A domain name with an A record pointing to the VPS IP
- Ports 80 and 443 open

### 1. Clone and configure

```bash
git clone https://github.com/TriMinhPham/shopkeeper.git /home/ubuntu/shopkeeper
cd /home/ubuntu/shopkeeper
cp .env.example .env
chmod 600 .env
```

Edit `.env` and set at minimum:

- `OPENROUTER_API_KEY` — your OpenRouter API key
- `SHOPKEEPER_SERVER_TOKEN` — a long random string for TCP auth

### 2. Build

```bash
docker compose build
```

This builds two images:
- `shopkeeper` — Python backend (heartbeat server, TCP, WebSocket, HTTP API)
- `shopkeeper-nginx` — nginx with the Next.js static frontend baked in

### 3. Set up TLS certificate

```bash
bash deploy/init-certs.sh yourdomain.com you@email.com
```

This obtains a Let's Encrypt certificate via ACME webroot challenge and patches `deploy/nginx.conf` with your domain.

### 4. Start

```bash
docker compose up -d
```

Verify:

```bash
docker compose ps                        # all services healthy
docker compose logs -f shopkeeper        # should show TCP/WS/HTTP listeners
curl -s https://yourdomain.com/api/health  # should return 200
```

### 5. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp     # certbot renewals
sudo ufw allow 443/tcp    # HTTPS + WSS
sudo ufw enable
```

### 6. Connect remotely (terminal client)

The terminal client uses raw TCP (port 9999), not HTTP. Use an SSH tunnel:

```bash
# Open tunnel (keep running)
ssh -N -L 9999:127.0.0.1:9999 ubuntu@yourdomain.com

# In another terminal
export SHOPKEEPER_HOST=127.0.0.1
export SHOPKEEPER_PORT=9999
export SHOPKEEPER_SERVER_TOKEN=your-token
python3 terminal.py --connect
```

Note: TCP port 9999 is not exposed to the internet. nginx only proxies HTTP/WebSocket traffic. The terminal client always connects via SSH tunnel.

### 7. Certificate renewal

Add a daily cron job:

```bash
sudo crontab -e
# Add:
0 3 * * * cd /home/ubuntu/shopkeeper && bash deploy/renew-certs.sh >> /var/log/shopkeeper-certbot.log 2>&1
```

### 8. Backups

Run manually or add to cron:

```bash
bash deploy/docker-backup.sh
```

Backups are saved to `./backups/` with 30-day retention. Add to cron for daily backups:

```bash
sudo crontab -e
# Add:
0 4 * * * cd /home/ubuntu/shopkeeper && bash deploy/docker-backup.sh >> /var/log/shopkeeper-backup.log 2>&1
```

### 9. Updating

```bash
git pull
docker compose build
docker compose up -d
```

### Architecture

```
                    Internet
                       │
              ┌────────┴────────┐
              │   nginx (:443)  │  TLS termination
              │                 │  Static frontend
              └───┬────┬────┬───┘
                  │    │    │
          /ws/    │    │    │  /api/
      ┌───────────┘    │    └───────────┐
      ▼                │                ▼
  shopkeeper:8765      │          shopkeeper:8080
  (WebSocket)          │          (HTTP REST API)
                       │
                  shopkeeper:9999
                  (TCP terminal)
```

### Ports

| Port | Protocol | Service | Purpose |
|------|----------|---------|---------|
| 80   | HTTP     | nginx   | ACME challenge + HTTPS redirect |
| 443  | HTTPS    | nginx   | TLS termination for all services |
| 9999 | TCP      | shopkeeper | Terminal client connection (internal) |
| 8765 | WebSocket | shopkeeper | Window UI live updates (internal) |
| 8080 | HTTP     | shopkeeper | Dashboard REST API (internal) |

Only ports 80 and 443 are exposed to the host. Internal ports communicate via Docker network.

### Troubleshooting

```bash
# Check service status
docker compose ps

# View logs
docker compose logs -f shopkeeper
docker compose logs -f nginx

# Restart
docker compose restart shopkeeper

# Full rebuild
docker compose down
docker compose build --no-cache
docker compose up -d

# Check nginx config
docker compose exec nginx nginx -t

# Check cert status
docker compose exec certbot certbot certificates
```

---

## Bare-metal (systemd) — alternative

For deployments without Docker. Uses systemd service + host nginx + certbot.

### Quick start

```bash
# Run the setup script as root on a fresh Ubuntu 24.04 VPS
bash deploy/setup.sh
```

This installs all dependencies, clones the repo, builds the frontend, configures nginx with TLS, sets up the systemd service, firewall, and daily backups.

### Manual setup

#### 1. Provision

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv nginx certbot python3-certbot-nginx
```

#### 2. Install app

```bash
git clone https://github.com/TriMinhPham/shopkeeper.git
cd shopkeeper
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data
```

#### 3. Configure

```bash
cp .env.example .env
chmod 600 .env
# Edit .env: set OPENROUTER_API_KEY and SHOPKEEPER_SERVER_TOKEN
```

#### 4. Systemd service

```bash
sudo cp deploy/shopkeeper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now shopkeeper
```

#### 5. Nginx

```bash
sudo cp nginx/shopkeeper.conf /etc/nginx/sites-available/shopkeeper
sudo ln -sf /etc/nginx/sites-available/shopkeeper /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo certbot --nginx -d yourdomain.com
sudo systemctl reload nginx
```

#### 6. Remote access (SSH tunnel, no TLS)

If not using nginx/TLS, bind to localhost and use an SSH tunnel:

```bash
# On the VPS, set in .env:
#   SHOPKEEPER_HOST=127.0.0.1

# On your local machine:
ssh -N -L 9999:127.0.0.1:9999 ubuntu@<vps-ip>

# Then connect:
python3 terminal.py --connect
```
