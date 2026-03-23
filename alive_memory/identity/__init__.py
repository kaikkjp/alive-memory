"""Deprecated — use alive_cognition.identity instead."""
from __future__ import annotations

import importlib
import warnings

warnings.warn(
    "alive_memory.identity is deprecated, use alive_cognition.identity",
    DeprecationWarning,
    stacklevel=2,
)
_mod = importlib.import_module("alive_cognition.identity")
_g = globals()
for _attr in dir(_mod):
    _g[_attr] = getattr(_mod, _attr)
del _mod, _g, _attr
