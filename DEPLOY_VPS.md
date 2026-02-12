# VPS Deployment (TCP Server)

## 1. Provision

```bash
sudo apt update
sudo apt install -y python3 python3-venv
```

## 2. Install app

```bash
git clone https://github.com/TriMinhPham/shopkeeper.git
cd shopkeeper
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data
```

## 3. Configure environment

```bash
cp .env.example .env
```

Set values in `.env`:

- `ANTHROPIC_API_KEY`
- `SHOPKEEPER_SERVER_TOKEN` (long random value)
- `SHOPKEEPER_HOST=127.0.0.1` (recommended; use SSH tunnel for remote access)
- `SHOPKEEPER_PORT=9999`

Optionally tighten file permissions:

```bash
chmod 600 .env
```

## 4. Run manually (smoke test on VPS)

```bash
set -a
source .env
set +a
python3 heartbeat_server.py
```

In another SSH session on the same VPS:

- Set `SHOPKEEPER_HOST=127.0.0.1`
- Set matching `SHOPKEEPER_PORT`
- Set matching `SHOPKEEPER_SERVER_TOKEN`
- Run `python3 terminal.py --connect`

## 5. Run as systemd service

Create `/etc/systemd/system/shopkeeper.service`:

```ini
[Unit]
Description=Shopkeeper Heartbeat Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/shopkeeper
EnvironmentFile=/home/ubuntu/shopkeeper/.env
ExecStart=/home/ubuntu/shopkeeper/.venv/bin/python3 /home/ubuntu/shopkeeper/heartbeat_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now shopkeeper
sudo systemctl status shopkeeper
```

## 6. Firewall

Allow SSH before enabling UFW:

```bash
sudo ufw allow OpenSSH
sudo ufw enable
```

## 7. Remote access (recommended: SSH tunnel, no public app port)

On your local machine:

```bash
ssh -N -L 9999:127.0.0.1:9999 ubuntu@<vps-ip>
```

Then run the client locally with:

- `SHOPKEEPER_HOST=127.0.0.1`
- matching `SHOPKEEPER_PORT` and `SHOPKEEPER_SERVER_TOKEN`
- `python3 terminal.py --connect`

If you intentionally expose the app on the public internet (`SHOPKEEPER_HOST=0.0.0.0`), explicitly open only that port and understand that traffic (including token auth) is plaintext unless you add transport security separately.

---

## Docker Deployment (with TLS)

Alternative to the systemd approach above. Uses Docker Compose with nginx for TLS termination.

### Prerequisites

- Docker and Docker Compose installed
- A domain name with an A record pointing to the VPS IP

### 1. Clone and configure

```bash
git clone https://github.com/TriMinhPham/shopkeeper.git
cd shopkeeper
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY and SHOPKEEPER_SERVER_TOKEN
chmod 600 .env
```

### 2. Set up TLS certificate

Edit `deploy/nginx.conf` — replace `YOURDOMAIN` with your actual domain.

Then obtain the initial certificate:

```bash
bash deploy/init-certs.sh yourdomain.com you@email.com
```

### 3. Start

```bash
docker compose up -d
```

Verify:

```bash
docker compose ps          # all services healthy
docker compose logs -f shopkeeper  # should show "Listening on 0.0.0.0:9999"
```

### 4. Connect remotely (TLS)

On your local machine:

```bash
export SHOPKEEPER_HOST=yourdomain.com
export SHOPKEEPER_PORT=443
export SHOPKEEPER_TLS=true
export SHOPKEEPER_SERVER_TOKEN=your-token
python3 terminal.py --connect
```

### 5. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp    # certbot renewals
sudo ufw allow 443/tcp   # TLS connections
sudo ufw enable
```

### 6. Backups

The SQLite database lives in a Docker volume (`shopkeeper-data`). Back it up:

```bash
docker compose exec shopkeeper python -c "
import sqlite3, shutil
shutil.copy2('/app/data/shopkeeper.db', '/app/data/backup.db')
" && docker compose cp shopkeeper:/app/data/backup.db ./backup-$(date +%F).db
```

### 7. Updating

```bash
git pull
docker compose build
docker compose up -d
```
