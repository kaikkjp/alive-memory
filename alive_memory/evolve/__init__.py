"""alive-memory evolve — source-level memory optimization via eval-driven mutation."""

from __future__ import annotations

from alive_memory.evolve.engine import evolve
from alive_memory.evolve.types import EvolveConfig, EvolveResult

__all__ = ["evolve", "EvolveConfig", "EvolveResult"]
