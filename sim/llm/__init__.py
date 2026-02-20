"""sim.llm — LLM backends for simulation.

MockCortex: deterministic, free, template-based.
CachedCortex: real LLM with response caching for reproducibility.
"""

from sim.llm.mock import MockCortex
from sim.llm.cached import CachedCortex

__all__ = ["MockCortex", "CachedCortex"]
