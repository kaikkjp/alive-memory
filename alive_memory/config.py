"""Configuration loader for alive-memory.

Supports loading from:
- YAML file path
- Python dict
- Defaults (alive_memory/defaults/alive_config.yaml)

Usage:
    config = AliveConfig()                          # defaults
    config = AliveConfig("path/to/config.yaml")     # from file
    config = AliveConfig({"memory": {"max_memories": 5000}})  # from dict
    config.get("memory.default_strength")           # → 0.5
    config.get("recall.default_limit", 10)          # → 5 (from config) or 10 (fallback)
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULTS_PATH = pathlib.Path(__file__).parent / "defaults" / "alive_config.yaml"


class AliveConfig:
    """Hierarchical configuration with dot-notation access."""

    def __init__(self, source: str | dict | None = None):
        self._data: dict = {}

        # Load defaults first
        if _DEFAULTS_PATH.exists():
            self._data = _load_yaml(_DEFAULTS_PATH)

        # Override with user config
        if isinstance(source, str):
            user = _load_yaml(pathlib.Path(source))
            _deep_merge(self._data, user)
        elif isinstance(source, dict):
            _deep_merge(self._data, source)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value using dot notation.

        Example: config.get("memory.default_strength") → 0.5
        """
        parts = key.split(".")
        current = self._data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def set(self, key: str, value: Any) -> None:
        """Set a config value using dot notation."""
        parts = key.split(".")
        current = self._data
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    @property
    def data(self) -> dict:
        """Raw config dict."""
        return self._data


def _load_yaml(path: pathlib.Path) -> dict:
    """Load a YAML file. Returns empty dict on error."""
    try:
        import yaml  # type: ignore[import-untyped]
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Fallback: parse simple YAML without pyyaml
        return _parse_simple_yaml(path)
    except Exception:
        logger.warning("Failed to load YAML config from %s", path, exc_info=True)
        return {}


def _parse_simple_yaml(path: pathlib.Path) -> dict:
    """Minimal YAML parser for the simple config format we use.

    Handles only nested key: value pairs with 2-space indentation.
    No arrays, no complex types.
    """
    result: dict = {}
    stack: list[tuple[int, dict]] = [(0, result)]

    for line in path.read_text().splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(stripped)
        if ":" not in stripped:
            continue

        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()

        # Remove inline comments
        if "#" in value:
            value = value[: value.index("#")].strip()

        # Pop stack to current indent level
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()

        parent = stack[-1][1]

        if value:
            # Leaf value — try to parse as number
            parent[key] = _parse_value(value)
        else:
            # Section header
            parent[key] = {}
            stack.append((indent, parent[key]))

    return result


def _parse_value(s: str) -> Any:
    """Parse a YAML scalar value."""
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s in ("null", "None", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s.strip("'\"")


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Mutates and returns base."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base
