"""Deprecated — use alive_cognition.meta instead."""
from __future__ import annotations

import importlib
import warnings

warnings.warn(
    "alive_memory.meta is deprecated, use alive_cognition.meta",
    DeprecationWarning,
    stacklevel=2,
)
_mod = importlib.import_module("alive_cognition.meta")
_g = globals()
for _attr in dir(_mod):
    _g[_attr] = getattr(_mod, _attr)
del _mod, _g, _attr
