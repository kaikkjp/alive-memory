"""Deprecated — use alive_cognition.meta.controller instead."""
from __future__ import annotations

import importlib
import warnings

warnings.warn(
    "alive_memory.meta.controller is deprecated, use alive_cognition.meta.controller",
    DeprecationWarning,
    stacklevel=2,
)
_mod = importlib.import_module("alive_cognition.meta.controller")
_g = globals()
for _attr in dir(_mod):
    _g[_attr] = getattr(_mod, _attr)
del _mod, _g, _attr
