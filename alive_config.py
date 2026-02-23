"""alive_config.py — Single loader for all ALIVE behavioral constants.

Two systems coexist:
  - DB-backed params: managed via db.parameters.p() — runtime-tunable,
    modification logging, bounds checking. ~85 cognitive constants.
  - YAML-backed params: managed via cfg() from this module — file-based,
    swappable for experiments via --config or ALIVE_CONFIG env var.
    ~25 structural/gating constants.

Usage in pipeline modules:
    from alive_config import cfg
    value = cfg('cortex.daily_cycle_cap')           # int/float
    value = cfg('habit_policy.journal.cooldown_cycles')  # nested access
"""

import os
import yaml


class ALIVEConfig:
    """Loads alive_config.yaml and provides dotpath access."""

    def __init__(self, path: str | None = None):
        if path is None:
            path = os.environ.get(
                'ALIVE_CONFIG',
                os.path.join(os.path.dirname(__file__), 'alive_config.yaml')
            )
        with open(path) as f:
            self._cfg = yaml.safe_load(f)

    def get(self, dotpath: str, default=None):
        """Access nested config: cfg('cortex.daily_cycle_cap')"""
        keys = dotpath.split('.')
        val = self._cfg
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def section(self, name: str) -> dict:
        """Get a top-level section as dict."""
        return self._cfg.get(name, {})

    def reload(self, path: str | None = None):
        """Reload config from disk (or a new path)."""
        if path is None:
            path = os.environ.get(
                'ALIVE_CONFIG',
                os.path.join(os.path.dirname(__file__), 'alive_config.yaml')
            )
        with open(path) as f:
            self._cfg = yaml.safe_load(f)


# Module-level singleton — import cfg() everywhere
_CONFIG: ALIVEConfig | None = None


def _ensure_loaded() -> ALIVEConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = ALIVEConfig()
    return _CONFIG


def cfg(dotpath: str, default=None):
    """Get a YAML-backed config value. Fast (no I/O after first load).

    Usage:
        from alive_config import cfg
        cap = cfg('cortex.daily_cycle_cap')
    """
    return _ensure_loaded().get(dotpath, default)


def cfg_section(name: str) -> dict:
    """Get a top-level config section as dict."""
    return _ensure_loaded().section(name)


def load_config(path: str | None = None):
    """Explicitly load or reload config from a specific path.

    Called by sim/__main__.py when --config is provided.
    """
    global _CONFIG
    _CONFIG = ALIVEConfig(path)
