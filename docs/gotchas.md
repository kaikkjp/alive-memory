# Gotchas

## Environment: Python version mismatch on macOS

The project requires Python 3.12+ but macOS ships with Python 3.9.6 (system Python). The `str | None` union type syntax used throughout `engine/db/` (e.g., `memory.py:19`) causes `TypeError` on Python < 3.10.

**Symptom:** `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` when running tests or importing engine modules.

**Fix:** Install Python 3.12 via Homebrew (`brew install python@3.12`) or pyenv. The project has no `pyproject.toml` or virtual environment config checked in — manage this locally.

## No linter configured

No `ruff`, `flake8`, `pylint`, or `mypy` is installed or configured (no `pyproject.toml`, `ruff.toml`, or `.flake8`). Linting is currently manual.

## docs/ vs root ARCHITECTURE.md

The root `ARCHITECTURE.md` is the canonical code map maintained by `scripts/update_docs.py`. The `docs/ARCHITECTURE.md` is a generated standalone reference. They serve different audiences — root is for agents working in the codebase, `docs/` is for external documentation.
