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
