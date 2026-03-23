"""Deprecated — use alive_cognition.thalamus instead."""
from __future__ import annotations

import importlib
import warnings

warnings.warn(
    "alive_memory.intake.thalamus is deprecated, use alive_cognition.thalamus",
    DeprecationWarning,
    stacklevel=2,
)
_mod = importlib.import_module("alive_cognition.thalamus")
_g = globals()
for _attr in dir(_mod):
    _g[_attr] = getattr(_mod, _attr)
del _mod, _g, _attr
