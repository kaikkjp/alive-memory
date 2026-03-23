"""Deprecated — use alive_cognition.meta.review instead."""
from __future__ import annotations

import importlib
import warnings

warnings.warn(
    "alive_memory.meta.review is deprecated, use alive_cognition.meta.review",
    DeprecationWarning,
    stacklevel=2,
)
_mod = importlib.import_module("alive_cognition.meta.review")
_g = globals()
for _attr in dir(_mod):
    _g[_attr] = getattr(_mod, _attr)
del _mod, _g, _attr
