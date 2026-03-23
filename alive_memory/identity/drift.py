"""Deprecated — use alive_cognition.identity.drift instead."""
from __future__ import annotations

import importlib
import warnings

warnings.warn(
    "alive_memory.identity.drift is deprecated, use alive_cognition.identity.drift",
    DeprecationWarning,
    stacklevel=2,
)
_mod = importlib.import_module("alive_cognition.identity.drift")
_g = globals()
for _attr in dir(_mod):
    _g[_attr] = getattr(_mod, _attr)
del _mod, _g, _attr
