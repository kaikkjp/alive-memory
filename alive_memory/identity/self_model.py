"""Deprecated — use alive_cognition.identity.self_model instead."""
from __future__ import annotations

import importlib
import warnings

warnings.warn(
    "alive_memory.identity.self_model is deprecated, use alive_cognition.identity.self_model",
    DeprecationWarning,
    stacklevel=2,
)
_mod = importlib.import_module("alive_cognition.identity.self_model")
_g = globals()
for _attr in dir(_mod):
    _g[_attr] = getattr(_mod, _attr)
del _mod, _g, _attr
