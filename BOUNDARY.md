# Repository Boundary — Engine / Demo Split

> TASK-101: This file documents the import boundary between platform code and instance-specific code.

## Directory Structure

```
alive/
  engine/         # Platform code — the ALIVE engine
  demo/           # Shopkeeper instance — one possible agent
  lounge/         # Manager dashboard (Next.js) — separate concern
  config/         # Platform-level YAML templates (no Python)
  tests/          # Test suite (imports from engine/)
  scripts/        # Utility scripts
  deploy/         # Deployment configs
  migrations/     # Database migrations
  assets/         # Runtime assets (sprites, images)
```

## The Rule

**`engine/` never imports from `demo/`.**

This is the only hard rule. Everything else follows from it.

## Why

AI agents reading the codebase see shop references and assume the system IS a shopkeeper app. By moving all shopkeeper-specific files into `demo/`, the engine code reads as a generic agent platform. The Shopkeeper becomes one possible configuration, not the identity of the system.

## What Lives Where

### `engine/` — Platform Code
All Python modules that implement the ALIVE agent engine:
- Cognitive pipeline (`pipeline/`)
- Database layer (`db/`)
- LLM integration (`llm/`)
- Server and heartbeat loop (`heartbeat.py`, `heartbeat_server.py`)
- Memory, identity, metrics, body, sleep systems
- Configuration loading (`config/`) — Python modules that READ config

### `demo/` — Shopkeeper Instance
Files specific to the default Shopkeeper agent:
- `demo/config/default_identity.yaml` — Shopkeeper's personality
- `demo/config/prompts.yaml` — Visual generation prompts
- `demo/window/` — Next.js frontend (shop UI)
- `demo/nginx/` — Nginx config for shopkeeper.tokyo
- `demo/content/` — Curated reading list
- `demo/scene-config.json` — Visual scene layout

### `config/` (top-level) — Platform Templates
- `default_digital_lifeform.yaml` — Blank-slate agent template
- No `__init__.py` — this is NOT a Python package

## How Config Loading Works

Engine code uses search chains to find config files:

1. **Environment variable** (e.g., `AGENT_IDENTITY`, `AGENT_CONFIG_DIR`)
2. **Module-relative** (works when YAML is co-located with Python)
3. **Repo-root fallback** (finds `demo/config/` or `config/`)

This lets the same engine code work with:
- The Shopkeeper (default, finds demo/config/)
- Custom agents (set env vars to point elsewhere)
- Tests (seed config in conftest.py)

## Verification

```bash
# No cross-boundary imports
grep -r "from demo" engine/   # must return nothing
grep -r "import demo" engine/ # must return nothing
```

## Known Coupling

`engine/config/feeds.py` contains a hardcoded path to `demo/content/readings.txt`. This is acknowledged technical debt — the feeds module also contains Shopkeeper-specific RSS URLs. A future task should extract feed configuration into the agent's config directory.
