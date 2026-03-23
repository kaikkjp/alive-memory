"""Deprecated — use alive_cognition.drives instead."""
from __future__ import annotations

import importlib
import warnings

warnings.warn(
    "alive_memory.intake.drives is deprecated, use alive_cognition.drives",
    DeprecationWarning,
    stacklevel=2,
)
_mod = importlib.import_module("alive_cognition.drives")
_g = globals()
for _attr in dir(_mod):
    _g[_attr] = getattr(_mod, _attr)
del _mod, _g, _attr
