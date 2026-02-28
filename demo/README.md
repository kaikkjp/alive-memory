# demo/ — Shopkeeper Instance

This directory contains files specific to the default Shopkeeper agent. The Shopkeeper is one possible configuration of the ALIVE engine (`engine/`).

## Contents

| Path | Purpose |
|------|---------|
| `config/default_identity.yaml` | Shopkeeper personality, voice rules, world config |
| `config/prompts.yaml` | Image generation prompts for the shop visual |
| `window/` | Next.js frontend — the shop window UI |
| `nginx/shopkeeper.conf` | Nginx config for shopkeeper.tokyo |
| `content/readings.txt` | Curated reading list for feed ingestion |
| `scene-config.json` | Visual scene layout (layers, sprites) |

## Creating a New Agent

To create a different agent, you don't modify demo/. Instead:

1. Create a new directory (e.g., `my-agent/`)
2. Add an `identity.yaml` based on `config/default_digital_lifeform.yaml`
3. Set `AGENT_CONFIG_DIR` and `AGENT_IDENTITY` environment variables
4. Run `engine/heartbeat_server.py`

See `scripts/create_agent.sh` for automated setup.
