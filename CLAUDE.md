# CLAUDE.md — alive-memory SDK

## Project

Standalone cognitive memory layer for persistent AI characters. Python 3.12+, SQLite (aiosqlite).

Extracted from the Shopkeeper engine into a reusable package.

## Repository Structure

```
alive_memory/       # The SDK package
tests/              # Integration tests
pyproject.toml      # Package config (hatchling)
```

## Boundary Rule

`alive_memory/` NEVER imports from application code. It is a standalone library.

## Running Tests

```bash
pytest
```

## Code Style

- Python asyncio throughout
- Type hints on function signatures
- `from __future__ import annotations` in every module
- ruff for linting (config in pyproject.toml)

## Package Build

```bash
pip install -e ".[dev]"     # dev install
pip install build && python -m build  # build wheel
```
