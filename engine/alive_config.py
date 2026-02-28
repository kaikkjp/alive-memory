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


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins on leaf conflicts."""
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


class ALIVEConfig:
    """Loads alive_config.yaml and provides dotpath access."""

    _BASE_PATH = os.path.join(os.path.dirname(__file__), 'alive_config.yaml')

    def __init__(self, override_path: str | None = None):
        # Always load the canonical base config first
        with open(self._BASE_PATH) as f:
            self._cfg = yaml.safe_load(f) or {}

        # ALIVE_CONFIG env var is an override layer (deep-merged, not a replacement)
        env_override = os.environ.get('ALIVE_CONFIG')
        if env_override and os.path.abspath(env_override) != os.path.abspath(self._BASE_PATH):
            with open(env_override) as f:
                overrides = yaml.safe_load(f) or {}
            self._cfg = _deep_merge(self._cfg, overrides)

        # CLI --config is a second override layer on top of env
        if override_path and os.path.abspath(override_path) != os.path.abspath(
                env_override or self._BASE_PATH):
            with open(override_path) as f:
                overrides = yaml.safe_load(f) or {}
            self._cfg = _deep_merge(self._cfg, overrides)

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

    def reload(self, override_path: str | None = None):
        """Reload config from disk, optionally with an override layer."""
        with open(self._BASE_PATH) as f:
            self._cfg = yaml.safe_load(f) or {}
        env_override = os.environ.get('ALIVE_CONFIG')
        if env_override and os.path.abspath(env_override) != os.path.abspath(self._BASE_PATH):
            with open(env_override) as f:
                overrides = yaml.safe_load(f) or {}
            self._cfg = _deep_merge(self._cfg, overrides)
        if override_path and os.path.abspath(override_path) != os.path.abspath(
                env_override or self._BASE_PATH):
            with open(override_path) as f:
                overrides = yaml.safe_load(f) or {}
            self._cfg = _deep_merge(self._cfg, overrides)


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


def load_config(override_path: str | None = None):
    """Load base config, optionally deep-merging an override file on top.

    Called by sim/__main__.py when --config is provided. The override
    file only needs to contain the keys it wants to change — all other
    values come from the base alive_config.yaml.
    """
    global _CONFIG
    _CONFIG = ALIVEConfig(override_path)
