"""Deprecated — use alive_cognition.identity.history instead."""
from __future__ import annotations

import importlib
import warnings

warnings.warn(
    "alive_memory.identity.history is deprecated, use alive_cognition.identity.history",
    DeprecationWarning,
    stacklevel=2,
)
_mod = importlib.import_module("alive_cognition.identity.history")
_g = globals()
for _attr in dir(_mod):
    _g[_attr] = getattr(_mod, _attr)
del _mod, _g, _attr
