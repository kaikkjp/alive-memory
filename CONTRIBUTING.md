# Contributing to alive-memory

## Development Setup

```bash
git clone git@github.com:TriMinhPham/Alive-sdk.git
cd Alive-sdk
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"
```

## Running Tests

```bash
pytest                    # all tests
pytest -v --tb=short      # verbose with short tracebacks
pytest tests/test_server.py  # server tests only (needs [server] extra)
```

## Code Style

- Python asyncio throughout — all I/O functions are `async`
- Type hints on function signatures
- `from __future__ import annotations` in every module
- Lint with ruff: `ruff check .`
- Type check with mypy: `mypy alive_memory --ignore-missing-imports`

## Making Changes

1. Create a branch from `alive-sdk-extraction`
2. Make your changes
3. Run `ruff check .` and `pytest`
4. Open a PR with a clear description of what changed and why

## Boundary Rule

`alive_memory/` is a standalone library. It must **never** import from application code (shopkeeper, agent runtime, etc.).

## Architecture

See [README.md](README.md) for the three-tier architecture overview. Key principle: recall is markdown-grep (Tier 2), vector search only happens during consolidation sleep (Tier 3).
